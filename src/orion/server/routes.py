"""Route handlers for the OpenAI-compatible API server."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from orion.core.types import Message, Role
from orion.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ComplexityInfo,
    DeltaMessage,
    ModelListResponse,
    ModelObject,
    StreamChoice,
    UsageInfo,
)

router = APIRouter()


def _to_messages(chat_messages) -> list[Message]:
    """Convert Pydantic ChatMessage objects to core Message objects."""
    messages = []
    for m in chat_messages:
        role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
        messages.append(
            Message(
                role=role,
                content=m.content or "",
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
        )
    return messages


# Base prompt for plain conversation (no tools). See the conversational branch
# in chat_completions for why the full tool-usage prompt is not sent there.
CONVERSATIONAL_PROMPT = (
    "You are Orion, a warm, capable personal AI assistant running locally on the "
    "user's own computer. Be natural and friendly, and keep replies short."
)
CONVERSATIONAL_HISTORY = 6

_SOCIAL_REPLY_WORDS = frozenset(
    "hi hello hey welcome good glad nice doing well help can how what thanks thank "
    "pleasure meet morning afternoon evening ready certainly absolutely".split()
)


def _social_reply_problem(content: str) -> str | None:
    """Describe why a short-social reply is unusable, otherwise return ``None``.

    The check deliberately rejects malformed output instead of prescribing an
    answer. A retry always remains a fresh model generation.
    """
    text = (content or "").strip()
    words = re.findall(r"[A-Za-z0-9']+", text.lower())
    if not words:
        return "it was empty or only punctuation"
    prompt_markers = ("live context", "user profile", "system prompt")
    if any(marker in text.lower() for marker in prompt_markers):
        return "it exposed prompt text"
    if len(words) == 1 and words[0] not in _SOCIAL_REPLY_WORDS:
        return "it only contained a name or fragment"
    if not set(words).intersection(_SOCIAL_REPLY_WORDS):
        return "it did not acknowledge the social message"
    return None


def _social_retry_messages(messages: list[Message], problem: str) -> list[Message]:
    """Insert a retry instruction before the conversation's first user turn."""
    retry = Message(
        role=Role.SYSTEM,
        content=(
            f"The previous draft failed quality checks because {problem}. "
            "Generate a fresh, complete, natural reply to the user's message. "
            "Do not output a name, a label, punctuation, or analysis by itself."
        ),
    )
    index = 1 if messages and messages[0].role == Role.SYSTEM else 0
    return [*messages[:index], retry, *messages[index:]]


def _generate_adaptive_social_reply(
    engine, model: str, req: ChatCompletionRequest
) -> dict[str, Any]:
    """Generate a social reply, retrying malformed drafts before they reach the user."""
    messages = _to_messages(req.messages)
    last_result: dict[str, Any] = {}
    for _ in range(3):
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        last_result = result
        problem = _social_reply_problem(str(result.get("content", "")))
        if problem is None:
            return result
        messages = _social_retry_messages(messages, problem)
    return last_result


def _retry_adaptive_social_reply(
    engine, model: str, req: ChatCompletionRequest, problem: str
) -> dict[str, Any]:
    """Regenerate after a streamed social draft has failed validation."""
    messages = _social_retry_messages(_to_messages(req.messages), problem)
    last_result: dict[str, Any] = {}
    for _ in range(2):
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        last_result = result
        retry_problem = _social_reply_problem(str(result.get("content", "")))
        if retry_problem is None:
            return result
        messages = _social_retry_messages(messages, retry_problem)
    return last_result


def _model_is_available(engine, model: str) -> bool:
    """Avoid hiding the normal error for a model that cannot be selected."""
    if not model:
        return True
    try:
        return model in engine.list_models()
    except Exception:
        # The normal engine call gives the clearest result when inventory is
        # unavailable, so it remains safe to use the guard in that case.
        return True


@router.post("/v1/chat/completions")
async def chat_completions(request_body: ChatCompletionRequest, request: Request):
    """Handle chat completion requests (streaming and non-streaming)."""
    idle_scheduler = getattr(request.app.state, "idle_learning_scheduler", None)
    if idle_scheduler is not None:
        idle_scheduler.touch()

    engine = request.app.state.engine
    agent = getattr(request.app.state, "agent", None)
    model = request_body.model

    # Captured before anything below (system prompt, session recap, memory
    # context) mutates request_body.messages -- memory capture needs the
    # user's actual raw question, not the context-injected/wrapped version
    # that gets spliced into the last user message further down. Without
    # this, each captured memory would embed the last one's full injected
    # content, growing into a self-referential, ever-larger blob every turn.
    raw_user_query = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            raw_user_query = m.content
            break

    # Small local models can lose the actual greeting when a one-word social
    # turn is surrounded by a long environment/profile prompt. This flag is
    # intentionally calculated from the unmodified user message, before any
    # context is added to the request.
    from orion.server.live_context import is_short_social_turn

    short_social = (
        not request_body.tools
        and is_short_social_turn(raw_user_query)
        and _model_is_available(engine, model)
    )

    # Inject system prompt if missing
    config = getattr(request.app.state, "config", None)
    if config is not None and request_body.messages:
        sys_prompt = getattr(config.agent, "system_prompt", "") or getattr(config.agent, "default_system_prompt", "")
        if sys_prompt and request_body.messages[0].role != "system":
            from orion.server.models import ChatMessage
            sys_msg = ChatMessage(role="system", content=sys_prompt)
            request_body.messages.insert(0, sys_msg)

    # Session Memory: if the user is resuming this thread after a long gap,
    # nudge the model to briefly acknowledge it using the history already
    # in this request — no extra LLM call needed. See session_recap.py.
    from orion.server.session_recap import mark_activity, should_inject_recap

    conversation_turns = [m for m in request_body.messages if m.role in ("user", "assistant")]
    if should_inject_recap(len(conversation_turns)):
        from orion.server.session_recap import RECAP_INSTRUCTION

        if request_body.messages and request_body.messages[0].role == "system":
            request_body.messages[0].content = (
                f"{request_body.messages[0].content}\n\n{RECAP_INSTRUCTION}"
            )
        else:
            from orion.server.models import ChatMessage
            request_body.messages.insert(0, ChatMessage(role="system", content=RECAP_INSTRUCTION))
    mark_activity()

    # Talking to Orion in the app is proof the user is here: clear a manual
    # "away" flag so it stops auto-replying to their contacts.
    try:
        from orion.core.activity import get_manual_away, set_manual_away

        if get_manual_away():
            set_manual_away(False)
    except Exception:
        logging.getLogger("orion.server").debug("Away flag check failed", exc_info=True)

    # Real clock, the user's stored name, and greeting rules -- see
    # server/live_context.py. Without it the model asked the user for the
    # date, called the user "Orion", and said "Greetings!" on every reply.
    try:
        from orion.server.live_context import build_live_context

        user_turns = sum(1 for m in request_body.messages if m.role == "user")
        live_note = build_live_context(
            raw_user_query,
            first_turn=user_turns <= 1,
            brief_social=short_social,
        )
        if request_body.messages and request_body.messages[0].role == "system":
            request_body.messages[0].content += f"\n\n{live_note}"
        else:
            from orion.server.models import ChatMessage

            request_body.messages.insert(0, ChatMessage(role="system", content=live_note))
    except Exception:
        logging.getLogger("orion.server").debug("Live context injection failed", exc_info=True)

    # Real affect-derived tone guidance -- see core/affect.py. Every input
    # here is a real signal (message urgency, actual recent trace outcomes,
    # actual memory-graph similarity); the result is a behavioral
    # instruction, never a first-person "I feel X" the model could parrot
    # back as an assertion of real feeling.
    try:
        from orion.core.affect import compute_affect, tone_instruction

        from starlette.concurrency import run_in_threadpool

        affect_state = await run_in_threadpool(
            compute_affect,
            text=raw_user_query,
            trace_store=getattr(request.app.state, "trace_store", None),
            memory_backend=getattr(request.app.state, "memory_backend", None),
        )
        tone_note = tone_instruction(affect_state)
        if tone_note:
            if request_body.messages and request_body.messages[0].role == "system":
                request_body.messages[0].content += f"\n\n{tone_note}"
            else:
                from orion.server.models import ChatMessage
                request_body.messages.insert(0, ChatMessage(role="system", content=tone_note))
    except Exception:
        logging.getLogger("orion.server").debug("Affect tone injection failed", exc_info=True)

    # Pending-action approval: parse ONLY the human's own latest message text
    # for explicit approve/deny tokens (e.g. "abc123 yes"). This is the sole
    # path by which a queued action (e.g. a drafted outgoing message) can be
    # approved — the model is never given record_decision as a callable tool,
    # specifically so it cannot approve its own proposed actions the way it
    # self-approved a shutdown earlier by just setting confirm=true itself.
    last_user_text = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            last_user_text = m.content
            break
    approval_executed = False
    if last_user_text:
        from orion.tools.proactive_tools import parse_approval_response

        decisions = parse_approval_response(last_user_text)
        if decisions:
            summary = "; ".join(
                f"{d['id']} {'approved' if d['approved'] else 'denied'}" for d in decisions
            )
            approved_ids = [d["id"] for d in decisions if d["approved"]]
            if approved_ids:
                # Run the approved actions here, not by asking the model to
                # call execute_pending_actions: a small model answered "send
                # it" with a paragraph about the draft and never sent anything.
                # The model only reports the real outcome.
                from orion.tools.proactive_tools import ExecutePendingActionsTool

                try:
                    from starlette.concurrency import run_in_threadpool

                    result = await run_in_threadpool(
                        ExecutePendingActionsTool().execute, action_ids=approved_ids
                    )
                    outcome = result.content
                except Exception as exc:
                    outcome = f"Execution failed: {exc}"
                note = (
                    f"[APPROVAL RECORDED AND EXECUTED: {summary}]\nReal result: {outcome}\n"
                    "Tell the user in one or two short sentences exactly what happened, based "
                    "only on that result. If it failed, say so plainly and give the reason; "
                    "never claim success the result does not show. Do not queue or execute "
                    "anything again."
                )
                approval_executed = True
            else:
                note = (
                    f"[APPROVAL RECORDED: {summary}] The user declined. Confirm in one short "
                    "sentence that it was cancelled. Do not queue it again."
                )
                approval_executed = True
            if request_body.messages and request_body.messages[0].role == "system":
                request_body.messages[0].content += f"\n\n{note}"
            else:
                from orion.server.models import ChatMessage
                request_body.messages.insert(0, ChatMessage(role="system", content=note))

    # Memory Condensation: enforce history limit to reduce tokens and encourage Obsidian usage
    if config is not None and getattr(config.agent, "max_history_messages", 0) > 0:
        limit = config.agent.max_history_messages
        msgs = request_body.messages
        # We need more than `limit` messages to truncate. We assume 1 system msg + limit.
        if len(msgs) > limit + 1:
            sys_msg = msgs[0] if msgs and msgs[0].role == "system" else None
            truncated = msgs[-limit:]
            if sys_msg is not None and (not truncated or truncated[0].role != "system"):
                truncated.insert(0, sys_msg)
            request_body.messages = truncated

    # Plain conversation ("can you hear me?") gets no tools and no recalled
    # memories. Recall on small talk only ever surfaced earlier small-talk
    # replies, which the model then parroted (a stray "Wi-Fi at 94%" answer
    # was echoed into every later greeting).
    from orion.tools.tool_router import is_conversational, wants_live_data

    # An approval that was just executed only needs its result reported.
    conversational = not request_body.tools and (
        approval_executed or is_conversational(raw_user_query)
    )
    if (
        conversational
        and not approval_executed
        and request_body.messages
        and request_body.messages[0].role == "system"
    ):
        # No tools are offered on this path, so the long tool-usage system
        # prompt is dead weight: on a 4B model half on CPU, every 2k prompt
        # tokens cost ~6.5 s before the first word. Keep the notes appended
        # after it (live context, tone, recap), swap the base for a short
        # persona, and keep only recent turns.
        system = request_body.messages[0]
        base_prompt = ""
        if config is not None:
            base_prompt = getattr(config.agent, "system_prompt", "") or getattr(
                config.agent, "default_system_prompt", ""
            )
        notes = system.content
        if base_prompt and notes.startswith(base_prompt):
            notes = notes[len(base_prompt):]
        system.content = (
            f"{CONVERSATIONAL_PROMPT}\n\n{notes.strip()}\n\nThis is casual conversation: "
            "answer the user's actual words directly in one or two short, natural spoken "
            "sentences. No markdown, no lists, and do not mention system status unless asked."
        )
        turns = [m for m in request_body.messages[1:] if m.role in ("user", "assistant")]
        request_body.messages = [system, *turns[-CONVERSATIONAL_HISTORY:]]

    # Inject memory context into messages before dispatching. Not for live
    # facts (weather, time, battery...): a remembered answer is stale, and the
    # model repeated it instead of calling the tool.
    memory_backend = getattr(request.app.state, "memory_backend", None)
    if (
        not conversational
        and not wants_live_data(raw_user_query)
        and config is not None
        and memory_backend is not None
        and config.agent.context_from_memory
        and request_body.messages
    ):
        try:
            from orion.tools.storage.context import ContextConfig, inject_context

            # Extract query from the last user message
            query_text = ""
            for m in reversed(request_body.messages):
                if m.role == "user" and m.content:
                    query_text = m.content
                    break

            if query_text:
                messages = _to_messages(request_body.messages)
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                from starlette.concurrency import run_in_threadpool

                enriched = await run_in_threadpool(
                    inject_context,
                    query_text,
                    messages,
                    memory_backend,
                    config=ctx_cfg,
                )
                # Rebuild request messages from enriched Message objects
                if len(enriched) > len(messages):
                    from orion.server.models import ChatMessage

                    new_msgs = []
                    for msg in enriched:
                        new_msgs.append(
                            ChatMessage(
                                role=msg.role.value,
                                content=msg.content,
                                name=msg.name,
                                tool_call_id=getattr(msg, "tool_call_id", None),
                            )
                        )
                    request_body.messages = new_msgs
        except Exception:
            logging.getLogger("orion.server").debug(
                "Memory context injection failed",
                exc_info=True,
            )

    # Run complexity analysis on the last user message
    complexity_info = None
    query_text_for_complexity = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            query_text_for_complexity = m.content
            break
    if query_text_for_complexity:
        try:
            from orion.learning.routing.complexity import (
                adjust_tokens_for_model,
                score_complexity,
            )

            cr = score_complexity(query_text_for_complexity)
            suggested = adjust_tokens_for_model(
                cr.suggested_max_tokens,
                model,
            )
            complexity_info = ComplexityInfo(
                score=cr.score,
                tier=cr.tier,
                suggested_max_tokens=suggested,
            )
            # Bump max_tokens when complexity suggests more than what
            # the client requested — never reduce below the request value.
            if suggested > request_body.max_tokens:
                request_body.max_tokens = suggested
        except Exception:
            logging.getLogger("orion.server").debug(
                "Complexity analysis failed",
                exc_info=True,
            )

    trace_store = getattr(request.app.state, "trace_store", None)
    agent_name = getattr(request.app.state, "agent_name", "") or ""

    if request_body.stream:
        bus = getattr(request.app.state, "bus", None)
        # Use the agent stream bridge only when tools are present (the
        # bridge runs agent.run() synchronously and word-splits the result,
        # so it can't stream tokens in real-time).  For plain chat, stream
        # directly from the engine for true token-by-token output.
        has_agent_tools = agent is not None and getattr(agent, "accepts_tools", False)
        # Plain conversation skips the tool agent entirely: streaming from
        # the engine gives a first token in about a second instead of a
        # tool-selection round trip plus word-split replay.
        if has_agent_tools and conversational:
            has_agent_tools = False
        if agent is not None and bus is not None and (request_body.tools or has_agent_tools):
            return await _handle_agent_stream(
                agent,
                bus,
                model,
                request_body,
                memory_backend=memory_backend,
                raw_user_query=raw_user_query,
                trace_store=trace_store,
                agent_name=agent_name,
            )
        if short_social:
            guarded = await _handle_adaptive_social_stream(
                engine,
                model,
                request_body,
                complexity_info=complexity_info,
                memory_backend=memory_backend,
                raw_user_query=raw_user_query,
                trace_store=trace_store,
            )
            if guarded is not None:
                return guarded
        return await _handle_stream(
            engine,
            model,
            request_body,
            complexity_info,
            memory_backend=memory_backend,
            raw_user_query=raw_user_query,
            trace_store=trace_store,
        )

    # Non-streaming: use agent if available, otherwise direct engine call
    if agent is not None:
        return _handle_agent(agent, model, request_body, complexity_info)

    bus = getattr(request.app.state, "bus", None)
    return _handle_direct(
        engine,
        model,
        request_body,
        bus=bus,
        complexity_info=complexity_info,
        social_guard=short_social,
    )


def _handle_direct(
    engine,
    model: str,
    req: ChatCompletionRequest,
    bus=None,
    complexity_info=None,
    social_guard: bool = False,
) -> ChatCompletionResponse:
    """Direct engine call without agent."""
    messages = _to_messages(req.messages)
    kwargs: dict[str, Any] = {}
    if req.tools:
        kwargs["tools"] = req.tools
    if social_guard:
        result = _generate_adaptive_social_reply(engine, model, req)
    elif bus:
        from orion.telemetry.wrapper import instrumented_generate

        result = instrumented_generate(
            engine,
            messages,
            model=model,
            bus=bus,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    else:
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    content = result.get("content", "")
    usage = result.get("usage", {})

    choice_msg = ChoiceMessage(role="assistant", content=content)
    # Include tool calls if present
    tool_calls = result.get("tool_calls")
    if tool_calls:
        choice_msg.tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            }
            for tc in tool_calls
        ]

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=choice_msg,
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


def _handle_agent(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
) -> ChatCompletionResponse:
    """Run through agent."""
    from orion.agents._stubs import AgentContext

    # Build context from prior messages
    ctx = AgentContext()
    if len(req.messages) > 1:
        prior = _to_messages(req.messages[:-1])
        for m in prior:
            ctx.conversation.add(m)

    # Last message is the input
    input_text = req.messages[-1].content if req.messages else ""

    # Override agent model for this request if the caller specified one
    original_model = agent._model
    if model:
        agent._model = model
    try:
        result = agent.run(input_text, context=ctx)
    finally:
        agent._model = original_model

    usage = UsageInfo(
        prompt_tokens=result.metadata.get("prompt_tokens", 0),
        completion_tokens=result.metadata.get("completion_tokens", 0),
        total_tokens=result.metadata.get("total_tokens", 0),
    )

    # Include audio metadata if the agent produced audio (e.g. morning digest)
    audio_meta = None
    audio_path = result.metadata.get("audio_path", "")
    if audio_path:
        from pathlib import Path

        from orion.server.models import AudioMeta

        if Path(audio_path).exists():
            audio_meta = AudioMeta(url="/api/digest/audio")

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content=result.content,
                    audio=audio_meta,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        complexity=complexity_info,
    )


async def _handle_agent_stream(
    agent,
    bus,
    model,
    req,
    memory_backend=None,
    raw_user_query="",
    trace_store=None,
    agent_name="",
):
    """Stream agent response with EventBus events via SSE."""
    from orion.server.stream_bridge import create_agent_stream

    return await create_agent_stream(
        agent,
        bus,
        model,
        req,
        memory_backend=memory_backend,
        raw_user_query=raw_user_query,
        trace_store=trace_store,
        agent_name=agent_name,
    )


async def _handle_adaptive_social_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    memory_backend=None,
    raw_user_query: str = "",
    trace_store=None,
):
    """Return a streamed, validated social reply, or ``None`` to use normal streaming.

    A social reply is generated before opening the SSE stream so an incomplete
    model draft cannot briefly appear in the UI. The accepted response is still
    model-generated; retries only give the model concrete quality feedback.
    """
    from orion.server.cloud_router import is_cloud_model

    # Cloud backends have their own direct streaming path. The reported issue
    # is with the bundled local model, and using its normal path preserves the
    # configured cloud provider's routing and authentication behavior.
    if is_cloud_model(model):
        return None

    try:
        candidate_tokens: list[str] = []
        async for token in engine.stream(
            _to_messages(req.messages),
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        ):
            candidate_tokens.append(token)
    except Exception:
        logging.getLogger("orion.server").warning(
            "Adaptive social reply stream failed; falling back to normal streaming",
            exc_info=True,
        )
        return None

    content = "".join(candidate_tokens)
    usage: dict[str, Any] = {}
    finish_reason = "stop"
    problem = _social_reply_problem(content)
    if problem is not None:
        from starlette.concurrency import run_in_threadpool

        try:
            result = await run_in_threadpool(
                _retry_adaptive_social_reply, engine, model, req, problem
            )
        except Exception:
            logging.getLogger("orion.server").warning(
                "Adaptive social reply retry failed; falling back to normal streaming",
                exc_info=True,
            )
            return None
        content = str(result.get("content", ""))
        usage = result.get("usage", {})
        finish_reason = result.get("finish_reason", "stop")
        # Regeneration is not token-streamed by an engine API, but preserve
        # ordinary SSE token boundaries for UI consumers.
        candidate_tokens = re.findall(r"\S+|\s+", content)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async def generate():
        import json as _json
        import threading
        import time as _time

        started_at = _time.time()
        role_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
        yield f"data: {role_chunk.model_dump_json()}\n\n"

        for token in candidate_tokens:
            content_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[StreamChoice(delta=DeltaMessage(content=token))],
            )
            yield f"data: {content_chunk.model_dump_json()}\n\n"

        finish_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason=finish_reason)],
        )
        finish_dict = _json.loads(finish_chunk.model_dump_json())
        finish_dict["telemetry"] = {"engine": "ollama"}
        if usage:
            finish_dict["usage"] = usage
        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()
        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

        # Keep the learning and trace behavior aligned with normal streaming.
        # These are fire-and-forget and never delay the reply.
        if raw_user_query and content:
            if memory_backend is not None:
                from orion.learning.memory_capture import capture_turn

                threading.Thread(
                    target=capture_turn,
                    kwargs={
                        "user_text": raw_user_query,
                        "assistant_text": content,
                        "memory_backend": memory_backend,
                        "channel": "chat",
                    },
                    daemon=True,
                ).start()
            if trace_store is not None:
                from orion.learning.trace_capture import record_chat_trace

                threading.Thread(
                    target=record_chat_trace,
                    kwargs={
                        "trace_store": trace_store,
                        "query": raw_user_query,
                        "result_content": content,
                        "model": model,
                        "engine": "ollama",
                        "started_at": started_at,
                        "total_tokens": usage.get(
                            "total_tokens", max(len(content) // 4, 1)
                        ),
                    },
                    daemon=True,
                ).start()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _handle_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    memory_backend=None,
    raw_user_query: str = "",
    trace_store=None,
):
    """Stream response using SSE format."""
    import time as _time

    from orion.server.cloud_router import (
        is_cloud_model,
        stream_cloud,
        stream_local,
    )

    messages = _to_messages(req.messages)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    turn_started_at = _time.time()

    # For memory capture once the stream completes. raw_user_query is the
    # user's actual question, captured before memory-context injection
    # rewrote the last user message -- capturing that enriched version
    # instead would make each memory embed the last one's full injected
    # content, snowballing into an ever-larger self-referential blob.
    last_user_text = raw_user_query
    reply_parts: list[str] = []

    # Route directly to the right backend — bypasses engine routing entirely
    # so broken MultiEngine state can never misdirect requests.
    use_cloud = is_cloud_model(model)

    async def generate():
        # Send role chunk first
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(role="assistant"),
                )
            ],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            # Cloud models → direct cloud API (reads keys from disk).
            # Local models → engine.stream() first so mock engines work in
            # tests.  Fall back to stream_local() only when the engine would
            # mis-route the request to a cloud backend (MultiEngine routing
            # confusion), which is detected by checking the routed engine's
            # is_cloud attribute.
            if use_cloud:
                token_iter = stream_cloud(
                    model, messages, req.temperature, req.max_tokens
                )
            else:
                # Use engine.stream() by default (preserves mock-engine
                # compatibility in tests).  Only fall back to stream_local()
                # when a real MultiEngine would mis-route the local model to a
                # cloud backend — detected via isinstance so mocks are not
                # accidentally matched.
                _use_local_fallback = False
                try:
                    from orion.engine.multi import MultiEngine

                    _inner = getattr(engine, "_inner", engine)
                    if isinstance(_inner, MultiEngine):
                        _routed = _inner._engine_for(model)
                        if _routed is not None and getattr(_routed, "is_cloud", False):
                            _use_local_fallback = True
                except Exception:
                    pass
                if _use_local_fallback:
                    token_iter = stream_local(
                        model, messages, req.temperature, req.max_tokens
                    )
                else:
                    token_iter = engine.stream(
                        messages,
                        model=model,
                        temperature=req.temperature,
                        max_tokens=req.max_tokens,
                    )
            async for token in token_iter:
                reply_parts.append(token)
                chunk = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            delta=DeltaMessage(content=token),
                        )
                    ],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as exc:
            # Surface errors as a content chunk so the frontend can
            # display them instead of silently failing.
            import logging

            logging.getLogger("orion.server").error(
                "Stream error: %s",
                exc,
                exc_info=True,
            )
            hint = str(exc)
            if "11434" in hint or "ollama" in hint.lower():
                hint = (
                    "Ollama failed to generate a reply. Restart the Ollama app, "
                    "free GPU/RAM, and use a smaller model (e.g. phi3:mini). "
                    f"Details: {exc}"
                )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {hint}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Send finish chunk with usage data if available
        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(),
                    finish_reason="stop",
                )
            ],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())

        # Tag the finish chunk with the correct engine label.
        # We use the routing decision (use_cloud) directly rather than
        # unwrapping the engine chain, which can be in a broken state.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"

        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()

        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

        # Fire-and-forget: turn this exchange into a durable, connected
        # memory (see memory_capture.py) and a real trace for the
        # auto-learning pipeline (see trace_capture.py). Both run after the
        # response has already been fully sent, on background threads, so
        # neither can add latency to or fail the actual reply the user is
        # waiting on.
        if last_user_text and reply_parts:
            import threading

            full_reply = "".join(reply_parts)

            if memory_backend is not None:
                from orion.learning.memory_capture import capture_turn

                threading.Thread(
                    target=capture_turn,
                    kwargs={
                        "user_text": last_user_text,
                        "assistant_text": full_reply,
                        "memory_backend": memory_backend,
                        "channel": "chat",
                    },
                    daemon=True,
                ).start()

            if trace_store is not None:
                from orion.learning.trace_capture import record_chat_trace

                threading.Thread(
                    target=record_chat_trace,
                    kwargs={
                        "trace_store": trace_store,
                        "query": last_user_text,
                        "result_content": full_reply,
                        "model": model,
                        "engine": "cloud" if use_cloud else "ollama",
                        "started_at": turn_started_at,
                        # No real token accounting on this path (the direct
                        # engine stream doesn't report usage) -- the same
                        # ~4-chars-per-token estimate already used as a
                        # fallback elsewhere (stream_bridge.py), not a made
                        # up number.
                        "total_tokens": max(len(full_reply) // 4, 1),
                    },
                    daemon=True,
                ).start()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/v1/models")
async def list_models(request: Request) -> ModelListResponse:
    """List locally installed models (Ollama).

    Cloud models are not included here — they live in the Cloud Models tab
    of the UI and are selected there, not from this endpoint.
    """
    from orion.server.cloud_router import is_cloud_model, list_local_models

    # Prefer engine.list_models() so mock engines work in tests.
    # Filter out any cloud model IDs that may appear via MultiEngine.
    # Fall back to direct Ollama query only when the engine returns nothing.
    engine = request.app.state.engine
    all_ids = engine.list_models()
    model_ids = [m for m in all_ids if not is_cloud_model(m)]
    if not model_ids:
        model_ids = await list_local_models()

    return ModelListResponse(
        data=[ModelObject(id=mid) for mid in model_ids],
    )


@router.post("/v1/models/pull")
async def pull_model(request: Request):
    """Pull / download a model from the Ollama registry."""
    body = await request.json()
    model_name = body.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="'model' field is required")

    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    # Only Ollama supports pulling
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(
            status_code=501,
            detail="Model pulling is only supported with the Ollama engine",
        )

    import httpx as _httpx

    host = getattr(engine, "_host", "http://127.0.0.1:11434")
    client = _httpx.Client(base_url=host, timeout=600.0)
    try:
        resp = client.post(
            "/api/pull",
            json={"name": model_name, "stream": False},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "ok", "model": model_name}


@router.delete("/v1/models/{model_name:path}")
async def delete_model(model_name: str, request: Request):
    """Delete a model from Ollama."""
    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(status_code=501, detail="Only supported with Ollama engine")

    import httpx as _httpx

    host = getattr(engine, "_host", "http://127.0.0.1:11434")
    client = _httpx.Client(base_url=host, timeout=30.0)
    try:
        resp = client.request(
            "DELETE",
            "/api/delete",
            json={"name": model_name},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "deleted", "model": model_name}


@router.post("/v1/cloud/reload")
async def reload_cloud_engine(request: Request):
    """Hot-reload cloud API keys and (re-)initialize the cloud engine.

    Called by the desktop app immediately after the user saves a cloud API
    key so that cloud models become available without a full app restart.
    """
    import os
    from pathlib import Path

    # Re-read ~/.orion/cloud-keys.env and update the running process env.
    keys_path = Path.home() / ".orion" / "cloud-keys.env"
    if keys_path.exists():
        for raw_line in keys_path.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

    # Try to build a fresh CloudEngine.
    try:
        from orion.engine.cloud import CloudEngine
        from orion.engine.multi import MultiEngine

        cloud = CloudEngine()
        if not cloud.health():
            return {
                "status": "no_cloud",
                "message": "No cloud models available (check API keys)",
            }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    # Locate the innermost engine, working through InstrumentedEngine layers.
    outer = request.app.state.engine
    inner = getattr(outer, "_inner", outer)

    if isinstance(inner, MultiEngine):
        # Replace or insert the cloud entry in the existing MultiEngine.
        new_engines = [(k, e) for k, e in inner._engines if k != "cloud"]
        new_engines.append(("cloud", cloud))
        inner._engines = new_engines
        inner._refresh_map()
    else:
        # Wrap the existing engine (which may be security-wrapped) with a new
        # MultiEngine that includes the cloud engine.
        engine_name = getattr(request.app.state, "engine_name", "local")
        new_multi = MultiEngine([(engine_name, inner), ("cloud", cloud)])
        if hasattr(outer, "_inner"):
            outer._inner = new_multi
        else:
            request.app.state.engine = new_multi
        request.app.state.engine_name = "multi"

    return {"status": "ok", "message": "Cloud engine reloaded"}


@router.get("/v1/savings")
async def savings(request: Request):
    """Return savings summary compared to cloud providers.

    Only includes telemetry from the current server session so that
    counters start at zero each time a new model + agent is launched.
    """
    from orion.core.config import DEFAULT_CONFIG_DIR
    from orion.server.savings import compute_savings, savings_to_dict
    from orion.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        empty = compute_savings(0, 0, 0)
        return savings_to_dict(empty)

    session_start = getattr(request.app.state, "session_start", None)

    agg = TelemetryAggregator(db_path)
    try:
        summary = agg.summary(since=session_start)
        # Exclude cloud model tokens from savings — only local
        # inference counts toward cost savings.
        _cloud_prefixes = (
            "gpt-",
            "o1-",
            "o3-",
            "o4-",
            "claude-",
            "gemini-",
            "openrouter/",
        )
        local_models = [
            m
            for m in summary.per_model
            if not any(m.model_id.startswith(p) for p in _cloud_prefixes)
        ]
        result = compute_savings(
            prompt_tokens=sum(m.prompt_tokens for m in local_models),
            completion_tokens=sum(m.completion_tokens for m in local_models),
            total_calls=sum(m.call_count for m in local_models),
            session_start=session_start if session_start else 0.0,
            prompt_tokens_evaluated=sum(
                m.prompt_tokens_evaluated for m in local_models
            ),
        )
        return savings_to_dict(result)
    finally:
        agg.close()


@router.post("/v1/telemetry/reset")
async def reset_telemetry():
    """Clear all stored telemetry records.

    Useful after updating token-counting methodology — clears
    historical records that were computed under the old rules so
    that the savings dashboard and leaderboard submissions start
    fresh with corrected values.
    """
    from orion.core.config import DEFAULT_CONFIG_DIR
    from orion.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        return {"status": "ok", "records_cleared": 0}

    agg = TelemetryAggregator(db_path)
    try:
        count = agg.clear()
    finally:
        agg.close()
    return {"status": "ok", "records_cleared": count}


@router.get("/v1/info")
async def server_info(request: Request):
    """Return server configuration: model, agent, engine."""
    agent = getattr(request.app.state, "agent", None)
    agent_id = getattr(agent, "agent_id", None) if agent else None
    # Fall back to configured agent name if agent didn't instantiate
    if agent_id is None:
        agent_id = getattr(request.app.state, "agent_name", None)
    return {
        "model": getattr(request.app.state, "model", ""),
        "agent": agent_id,
        "engine": getattr(request.app.state, "engine_name", ""),
    }


@router.get("/v1/learning/status")
async def learning_status(request: Request):
    """Status of the idle-triggered background learning scheduler, if enabled."""
    scheduler = getattr(request.app.state, "idle_learning_scheduler", None)
    if scheduler is None:
        return {"enabled": False}
    return {"enabled": True, **scheduler.status}


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    engine = request.app.state.engine
    healthy = engine.health()
    if not healthy:
        raise HTTPException(status_code=503, detail="Engine unhealthy")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Channel endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/channels")
async def list_channels(request: Request):
    """List available messaging channels."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"channels": [], "message": "Channel bridge not configured"}
    channels = bridge.list_channels()
    return {"channels": channels, "status": bridge.status().value}


@router.post("/v1/channels/send")
async def channel_send(request: Request):
    """Send a message to a channel."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Channel bridge not configured")

    body = await request.json()
    channel_name = body.get("channel", "")
    content = body.get("content", "")
    conversation_id = body.get("conversation_id", "")

    if not channel_name or not content:
        raise HTTPException(
            status_code=400,
            detail="'channel' and 'content' are required",
        )

    ok = bridge.send(channel_name, content, conversation_id=conversation_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message")
    return {"status": "sent", "channel": channel_name}


@router.get("/v1/channels/status")
async def channel_status(request: Request):
    """Return channel bridge connection status."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"status": "not_configured"}
    return {"status": bridge.status().value}


def _whatsapp_channel(request: Request):
    """Reach into the real WhatsAppBaileysChannel behind the ChannelBridge
    wrapper -- app.state.channel_bridge is a multiplexer over one channel
    per configured type (see server/channel_bridge.py's `_channels` dict),
    not the WhatsApp channel object itself.
    """
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return None
    channels = getattr(bridge, "_channels", {}) or {}
    return channels.get("whatsapp_baileys")


@router.get("/v1/channels/whatsapp/qr")
async def whatsapp_qr(request: Request) -> dict:
    """Current WhatsApp pairing state: connection status, and the raw QR
    pairing string (if the bridge is mid-handshake and hasn't linked yet)
    for the frontend to render into a scannable code. Real state only --
    no QR value once actually connected, none at all if the bridge was
    never started.
    """
    ch = _whatsapp_channel(request)
    if ch is None:
        return {"status": "not_configured", "qr": None}
    return {"status": ch.status().value, "qr": getattr(ch, "qr_code", "") or None}


@router.post("/v1/channels/whatsapp/connect")
async def whatsapp_connect(request: Request) -> dict:
    """(Re)start the WhatsApp bridge so it begins the pairing handshake --
    poll /v1/channels/whatsapp/qr afterward for the code to scan. Safe to
    call when already connected/connecting: connect() is a no-op in that
    case (see WhatsAppBaileysChannel.connect).
    """
    ch = _whatsapp_channel(request)
    if ch is None:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp channel is not configured. Enable it in config.toml first.",
        )
    import asyncio

    await asyncio.to_thread(ch.connect)
    return {"status": ch.status().value}


# ---------------------------------------------------------------------------
# Security scan endpoint
# ---------------------------------------------------------------------------


@router.get("/v1/security/scan")
async def security_scan():
    """Run a read-only security environment audit and return findings."""
    from orion.cli.scan_cmd import PrivacyScanner

    scanner = PrivacyScanner()
    results = scanner.run_all()
    return {
        "has_warnings": any(r.status == "warn" for r in results),
        "has_failures": any(r.status == "fail" for r in results),
        "findings": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "platform": r.platform,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Clipboard Intelligence — quick one-shot transforms for the floating panel
# ---------------------------------------------------------------------------

_CLIPBOARD_ACTION_PROMPTS: dict[str, str] = {
    "translate": (
        "Translate the following text to {target_language}. "
        "Output ONLY the translation, nothing else."
    ),
    "summarize": (
        "Summarize the following text in 2-3 concise sentences. "
        "Output ONLY the summary, nothing else."
    ),
    "explain": (
        "Explain the following text in plain, simple language a beginner "
        "could understand. Output ONLY the explanation, nothing else."
    ),
    "fix": (
        "Fix any spelling, grammar, and phrasing issues in the following text. "
        "Preserve the original meaning and tone. Output ONLY the corrected text, "
        "nothing else."
    ),
}


@router.post("/v1/clipboard/action")
async def clipboard_action(request: Request):
    """Run a quick transform (translate/summarize/explain/fix) on clipboard text.

    Deliberately bypasses the main chat_completions pipeline (no memory
    injection, no conversation history, no tool-calling loop) since this is
    a fast, stateless, single-shot transform for the floating clipboard panel.
    """
    body = await request.json()
    text = (body.get("text") or "").strip()
    action = (body.get("action") or "").strip().lower()
    target_language = (body.get("target_language") or "English").strip()

    if not text:
        raise HTTPException(status_code=400, detail="'text' is required")
    if action not in _CLIPBOARD_ACTION_PROMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"'action' must be one of: {', '.join(_CLIPBOARD_ACTION_PROMPTS)}",
        )

    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="No inference engine configured")

    model = getattr(request.app.state, "model", None) or "llama3.2:3b"
    system_prompt = _CLIPBOARD_ACTION_PROMPTS[action].format(target_language=target_language)

    messages = [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(role=Role.USER, content=text[:8000]),
    ]

    try:
        import asyncio

        result = await asyncio.to_thread(
            engine.generate, messages, model=model, temperature=0.3, max_tokens=800
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Clipboard action failed: {exc}") from exc

    return {"action": action, "result": (result.get("content") or "").strip()}


__all__ = ["router"]
