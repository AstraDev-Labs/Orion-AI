"""Bridge sync agent.run() + EventBus events to an async SSE generator.

Subscribes to EventBus callbacks that push events into an asyncio.Queue,
runs agent.run() in a background thread, and yields SSE-formatted strings
from the queue for consumption by FastAPI's StreamingResponse.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator

from fastapi.responses import StreamingResponse

from orion.agents._stubs import AgentContext, BaseAgent
from orion.core.events import Event, EventBus, EventType
from orion.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    DeltaMessage,
    StreamChoice,
    UsageInfo,
)

# EventTypes we subscribe to and their corresponding SSE event names
_EVENT_MAP = {
    EventType.AGENT_TURN_START: "agent_turn_start",
    EventType.INFERENCE_START: "inference_start",
    EventType.INFERENCE_END: "inference_end",
    EventType.TOOL_CALL_START: "tool_call_start",
    EventType.TOOL_CALL_END: "tool_call_end",
}

# Sentinel signalling that the agent thread has finished
_DONE = object()


class _Delta:
    """Reply text streamed by the agent while it runs."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


def _estimate_prompt_tokens(messages: list) -> int:
    """Estimate prompt tokens from request messages (incl. system, user, context).

    Uses ~4 chars per token heuristic. Ensures system and all context are counted.
    """
    total = 0
    for m in messages:
        text = getattr(m, "content", None) or ""
        if isinstance(text, str):
            total += max(1, len(text) // 4)
        # Tool call messages may have structured content; still count what we can
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                fn = tc.get("function") if isinstance(tc, dict) else {}
                args = fn.get("arguments", "") if isinstance(fn, dict) else ""
                total += max(1, len(str(args)) // 4)
    return total


class AgentStreamBridge:
    """Bridge between a synchronous agent and an async SSE stream.

    Pattern:
    1. Subscribe EventBus callbacks that push events into an asyncio.Queue
       via ``loop.call_soon_threadsafe()``.
    2. Run ``agent.run()`` in a thread via ``asyncio.to_thread()``.
    3. Async generator reads from queue and yields SSE-formatted strings.
    4. Unsubscribe from EventBus in ``finally`` block.
    """

    def __init__(
        self,
        agent: BaseAgent,
        bus: EventBus,
        model: str,
        request: ChatCompletionRequest,
        memory_backend=None,
        raw_user_query: str = "",
        trace_store=None,
        agent_name: str = "",
    ) -> None:
        self._agent = agent
        self._bus = bus
        self._model = model
        self._request = request
        self._memory_backend = memory_backend
        self._trace_store = trace_store
        self._agent_name = agent_name
        # The user's actual question, captured before memory-context
        # injection rewrote the last user message -- see routes.py. Using
        # self._request.messages[-1].content here instead would capture the
        # enriched/wrapped prompt, not the real question.
        self._raw_user_query = raw_user_query
        self._chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self._queue: asyncio.Queue = asyncio.Queue()
        self._callbacks: dict[EventType, object] = {}
        self._started_at = time.time()
        # Reply text the agent streamed while it ran (see _on_delta).
        self._streamed_text = ""
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_callback(self, event_type: EventType):
        """Create a callback that pushes the event onto the async queue."""
        loop = asyncio.get_event_loop()

        def _cb(event: Event) -> None:
            loop.call_soon_threadsafe(self._queue.put_nowait, event)

        self._callbacks[event_type] = _cb
        return _cb

    def _subscribe_all(self) -> None:
        """Subscribe to all relevant EventBus event types."""
        for et in _EVENT_MAP:
            self._bus.subscribe(et, self._make_callback(et))

    def _unsubscribe_all(self) -> None:
        """Remove all registered subscriptions."""
        for et, cb in self._callbacks.items():
            self._bus.unsubscribe(et, cb)
        self._callbacks.clear()

    def _content_chunk(self, text: str) -> str:
        chunk = ChatCompletionChunk(
            id=self._chunk_id,
            model=self._model,
            choices=[StreamChoice(delta=DeltaMessage(content=text))],
        )
        return f"data: {chunk.model_dump_json()}\n\n"

    def _format_named_event(self, name: str, data: dict) -> str:
        """Format an SSE event with an explicit ``event:`` field."""
        return f"event: {name}\ndata: {json.dumps(data)}\n\n"

    def _run_agent(self) -> object:
        """Execute the agent synchronously (called via asyncio.to_thread)."""
        ctx = AgentContext()
        # Build conversation context from prior messages
        if len(self._request.messages) > 1:
            from orion.core.types import Message, Role

            for m in self._request.messages[:-1]:
                role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
                ctx.conversation.add(
                    Message(
                        role=role,
                        content=m.content or "",
                        name=m.name,
                        tool_call_id=m.tool_call_id,
                    )
                )

        input_text = (
            self._request.messages[-1].content if self._request.messages else ""
        )

        # Override agent model for this request if the caller specified one
        original_model = self._agent._model
        if self._model:
            self._agent._model = self._model
        try:
            if getattr(self._agent, "supports_delta_stream", False):
                return self._agent.run(input_text, context=ctx, on_delta=self._on_delta)
            return self._agent.run(input_text, context=ctx)
        finally:
            self._agent._model = original_model

    def _on_delta(self, text: str) -> None:
        """Called from the agent's thread with reply text as the model writes it."""
        if text and self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, _Delta(text))

    # ------------------------------------------------------------------
    # Public streaming interface
    # ------------------------------------------------------------------

    async def stream(self) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE-formatted strings."""
        self._subscribe_all()

        # Kick off agent.run() in a background thread
        loop = asyncio.get_event_loop()
        self._loop = loop
        agent_task = asyncio.ensure_future(asyncio.to_thread(self._run_agent))

        def _on_done(fut):
            loop.call_soon_threadsafe(self._queue.put_nowait, _DONE)

        agent_task.add_done_callback(_on_done)

        try:
            # Send initial role chunk (OpenAI-compatible)
            first_chunk = ChatCompletionChunk(
                id=self._chunk_id,
                model=self._model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(role="assistant"),
                    )
                ],
            )
            yield f"data: {first_chunk.model_dump_json()}\n\n"

            # Drain queue until the agent finishes
            while True:
                item = await self._queue.get()

                if item is _DONE:
                    break

                if isinstance(item, _Delta):
                    self._streamed_text += item.text
                    yield self._content_chunk(item.text)
                    continue

                if isinstance(item, Event):
                    sse_name = _EVENT_MAP.get(item.event_type)
                    if sse_name:
                        yield self._format_named_event(sse_name, item.data)

            # Agent is done -- retrieve result
            try:
                agent_result = agent_task.result()
            except Exception as exc:
                import logging

                logger = logging.getLogger("orion.server")
                logger.error("Agent stream error: %s", exc, exc_info=True)

                error_str = str(exc)
                if "context length" in error_str.lower() or (
                    "400" in error_str and "too long" in error_str.lower()
                ):
                    error_content = (
                        "The input is too long for the model's context window. "
                        "Please try a shorter message."
                    )
                elif "400" in error_str:
                    error_content = f"The model returned an error: {error_str}"
                else:
                    error_content = f"Sorry, an error occurred: {error_str}"
                error_chunk = ChatCompletionChunk(
                    id=self._chunk_id,
                    model=self._model,
                    choices=[
                        StreamChoice(
                            delta=DeltaMessage(content=error_content),
                            finish_reason="stop",
                        )
                    ],
                )
                yield f"data: {error_chunk.model_dump_json()}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Emit tool results metadata if any
            tool_results_data = []
            for tr in agent_result.tool_results:
                tool_results_data.append(
                    {
                        "tool_name": tr.tool_name,
                        "success": tr.success,
                        "output": tr.content,
                        "latency_ms": tr.latency_seconds * 1000,
                    }
                )

            if tool_results_data:
                yield self._format_named_event(
                    "tool_results",
                    {"results": tool_results_data},
                )

            # Stream the agent's own final answer. This used to re-generate a
            # fresh reply with engine.stream_full() from the request messages
            # alone -- without the tool calls or their results -- so after
            # Orion had already opened YouTube it replied "Would you like me to
            # proceed?", and every tool turn paid for a second full generation.
            content = agent_result.content or ""
            # The agent streamed its reply as the model wrote it. Only send the
            # final answer here when it was not already part of that stream
            # (an agent without delta support, or a fallback message).
            already_streamed = bool(content.strip()) and self._streamed_text.rstrip().endswith(content.strip())

            if content and not already_streamed:
                if self._streamed_text.strip():
                    content_to_send = "\n\n" + content
                else:
                    content_to_send = content
                words = content_to_send.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else " " + word
                    yield self._content_chunk(token)
                    await asyncio.sleep(0.004)

            # Final chunk: finish_reason + usage
            prompt_tokens = agent_result.metadata.get("prompt_tokens", 0)
            completion_tokens = agent_result.metadata.get(
                "completion_tokens",
                0,
            )
            total_tokens = agent_result.metadata.get("total_tokens", 0)
            if total_tokens == 0:
                # Fallback: estimate from request messages (incl. system) + content
                completion_tokens = max(len(content) // 4, 1)
                prompt_tokens = _estimate_prompt_tokens(self._request.messages)
                total_tokens = prompt_tokens + completion_tokens

            final_chunk = ChatCompletionChunk(
                id=self._chunk_id,
                model=self._model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(),
                        finish_reason="stop",
                    )
                ],
            )
            final_data = json.loads(final_chunk.model_dump_json())
            final_data["usage"] = UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ).model_dump()
            yield f"data: {json.dumps(final_data)}\n\n"

            yield "data: [DONE]\n\n"

            # Fire-and-forget: turn this exchange into a durable, connected
            # memory (see memory_capture.py) -- same as the plain (no-agent)
            # streaming path in routes.py. Runs after the response has
            # already been sent, so it can't add latency or fail the reply.
            last_user_text = self._raw_user_query
            if self._memory_backend is not None and last_user_text and content:
                import threading

                from orion.learning.memory_capture import capture_turn

                threading.Thread(
                    target=capture_turn,
                    kwargs={
                        "user_text": last_user_text,
                        "assistant_text": content,
                        "memory_backend": self._memory_backend,
                        "channel": "chat",
                    },
                    daemon=True,
                ).start()

            # Same fire-and-forget pattern for the auto-learning pipeline's
            # trace store -- see trace_capture.py for why this was needed at
            # all (nothing ever recorded a trace for interactive chat before).
            if self._trace_store is not None and last_user_text and content:
                import threading

                from orion.learning.trace_capture import record_chat_trace

                threading.Thread(
                    target=record_chat_trace,
                    kwargs={
                        "trace_store": self._trace_store,
                        "query": last_user_text,
                        "result_content": content,
                        "model": self._model,
                        "engine": "ollama",
                        "started_at": self._started_at,
                        "total_tokens": total_tokens,
                        "agent": self._agent_name,
                    },
                    daemon=True,
                ).start()

        except Exception:
            # On error, cancel the agent task if still running
            if not agent_task.done():
                agent_task.cancel()
            raise
        finally:
            self._unsubscribe_all()


async def create_agent_stream(
    agent: BaseAgent,
    bus: EventBus,
    model: str,
    request: ChatCompletionRequest,
    memory_backend=None,
    raw_user_query: str = "",
    trace_store=None,
    agent_name: str = "",
) -> StreamingResponse:
    """Create an AgentStreamBridge and return a FastAPI StreamingResponse."""
    bridge = AgentStreamBridge(
        agent,
        bus,
        model,
        request,
        memory_backend=memory_backend,
        raw_user_query=raw_user_query,
        trace_store=trace_store,
        agent_name=agent_name,
    )
    return StreamingResponse(
        bridge.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


__all__ = ["AgentStreamBridge", "create_agent_stream"]
