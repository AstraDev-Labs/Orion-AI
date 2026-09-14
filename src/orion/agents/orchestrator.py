"""OrchestratorAgent — multi-turn agent with tool-calling loop.

Supports two modes:

- **function_calling** (default): Uses OpenAI-format tool definitions and
  parses ``tool_calls`` from the engine response.
- **structured**: Uses a THOUGHT/TOOL/INPUT/FINAL_ANSWER text format
  (like ReAct) with a canonical system prompt from the orchestrator
  prompt registry.  This is the format used by the SFT/GRPO training
  pipelines, making the Orchestrator a distinctive trainable agent type.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
import re
from typing import Any, Callable, List, Optional

from orion.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from orion.core.events import EventBus
from orion.core.registry import AgentRegistry
from orion.core.types import Message, Role, ToolCall, ToolResult
from orion.engine._stubs import InferenceEngine
from orion.tools._stubs import BaseTool

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


logger = logging.getLogger(__name__)


# Tools that only look things up. The model may call these even when the
# router did not offer them for the request (a follow-up lookup it needs).
# Anything else changes something -- away mode, volume, a message draft, a
# file, an install -- and runs only when offered for the user's own request:
# asked about the weather, a small model once also switched on away mode (it
# knew the name from the system prompt), which starts auto-replying to the
# user's WhatsApp contacts.
_LOOKUP_TOOLS = frozenset({
    "web_search", "web_fetch", "calculator", "system_info", "situation_awareness",
    "memory_search", "memory_retrieve", "obsidian_search_notes", "file_read",
    "kg_query", "kg_neighbors", "get_pending_actions", "check_permission",
    "browser_extract", "browser_axtree", "browser_screenshot", "vision_capture",
    "git_status", "git_diff", "git_log", "think",
})


def _unoffered_call_result(tool_name: str, offered: set[str], known: set[str]) -> Optional[ToolResult]:
    """A refusal for a state-changing tool the router did not offer, else None.

    Names outside `known` (no such tool) are left to the executor, which
    points the model at propose_new_tool rather than a dead end.
    """
    if not offered or tool_name in offered or tool_name in _LOOKUP_TOOLS or tool_name not in known:
        return None
    return ToolResult(
        tool_name=tool_name,
        content=(
            f"Not run: '{tool_name}' changes something, and the user's message did not ask "
            "for it. Do not call it again for this request. Answer what the user actually "
            "asked; if they want this done too, they can say so."
        ),
        success=False,
    )


def _streams_tool_calls(engine: Any, model: str) -> bool:
    """True when `engine` streams tool calls, not just text.

    The base InferenceEngine.stream_full wraps stream() and silently drops
    tools, so streaming a tool turn through it would never call a tool.
    Follows telemetry/guardrail wrappers (_inner/_engine) and MultiEngine
    routing down to the engine that actually serves `model`.
    """
    current = engine
    for _ in range(8):
        route = getattr(current, "_engine_for", None)
        if callable(route):
            try:
                current = route(model)
            except Exception:
                return False
            continue
        inner = getattr(current, "_inner", None)
        if not isinstance(inner, InferenceEngine):
            inner = getattr(current, "_engine", None)
        if isinstance(inner, InferenceEngine):
            current = inner
            continue
        return type(current).stream_full is not InferenceEngine.stream_full
    return False


@AgentRegistry.register("orchestrator")
class OrchestratorAgent(ToolUsingAgent):
    """Multi-turn agent that routes between tools and the LLM.

    Implements a tool-calling loop:
    1. Send messages with tool definitions to the engine.
    2. If the response contains tool_calls, execute them and loop.
    3. If no tool_calls, return the final answer.
    4. Stop after ``max_turns`` iterations.

    In **structured** mode the agent instead uses a
    ``THOUGHT: / TOOL: / INPUT: / FINAL_ANSWER:`` text protocol
    identical to the format used by the orchestrator SFT/GRPO
    training pipelines.
    """

    agent_id = "orchestrator"
    # run() accepts on_delta=callable: reply text is passed along as the model
    # writes it (see _generate_streaming), instead of only once a turn is done.
    supports_delta_stream = True
    _default_temperature = 0.7
    _default_max_tokens = 1024
    _default_max_turns = 10

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mode: str = "function_calling",
        system_prompt: Optional[str] = None,
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
        max_tools_per_request: Optional[int] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )
        self._mode = mode
        if self._mode == "function_calling" and "orion" in str(model).lower():
            self._mode = "structured"

        self._system_prompt = system_prompt
        self._parallel_tools = parallel_tools
        if max_tools_per_request is None:
            try:
                from orion.core.config import load_config

                max_tools_per_request = load_config().agent.max_tools_per_request
            except Exception:
                max_tools_per_request = 12
        self._max_tools_per_request = max_tools_per_request
        try:
            from orion.core.config import load_config

            self._time_budget_s = float(load_config().agent.max_seconds)
        except Exception:
            self._time_budget_s = 60.0

    @traceable(name="OrchestratorAgent.run", run_type="chain")
    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        if self._mode == "structured":
            return self._run_structured(input, context, **kwargs)
        return self._run_function_calling(input, context, **kwargs)

    # ------------------------------------------------------------------
    # Structured mode (THOUGHT/TOOL/INPUT/FINAL_ANSWER)
    # ------------------------------------------------------------------

    def _run_structured(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        from orion.learning.intelligence.orchestrator.prompt_registry import (
            build_system_prompt,
        )

        base_structured_prompt = build_system_prompt(tools=self._tools)

        # Build system prompt
        if self._system_prompt:
            sys_prompt = f"{self._system_prompt}\n\n{base_structured_prompt}"
        else:
            sys_prompt = base_structured_prompt

        messages = self._build_messages(input, context, system_prompt=sys_prompt)

        all_tool_results: list[ToolResult] = []
        turns = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            result = self._generate(messages)
            content = result.get("content", "")

            # Was a bare print() on every structured turn, which dumped the raw
            # model output to stdout in production -- including into the CLI's
            # rendered output and the server log. Kept as debug-level logging.
            logger.debug("structured turn %d raw content: %s", turns, content)

            parsed = self._parse_structured_response(content)

            # FINAL_ANSWER -> done
            if parsed["final_answer"]:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=parsed["final_answer"],
                    tool_results=all_tool_results,
                    turns=turns,
                )

            # TOOL -> execute
            if parsed["tool"]:
                messages.append(Message(role=Role.ASSISTANT, content=content))

                import json
                import re

                raw_input = parsed["input"]
                arguments = "{}"
                if raw_input:
                    try:
                        json.loads(raw_input)
                        arguments = raw_input
                    except Exception:
                        tool_inst = next((t for t in self._tools if t.spec.name == parsed["tool"]), None)
                        if tool_inst and tool_inst.spec.parameters:
                            props = tool_inst.spec.parameters.get("properties", {})
                            if props:
                                first_param = list(props.keys())[0]

                                # Try comma-separated key=value pairs
                                # e.g. "platform=youtube_music, mood=happy, language=tamil"
                                kv_pairs = re.findall(r'(\w+)\s*=\s*([^,]+)', raw_input)
                                if kv_pairs and any(k in props for k, _ in kv_pairs):
                                    parsed_args = {}
                                    for k, v in kv_pairs:
                                        v = v.strip().strip("'\"")
                                        if k in props:
                                            parsed_args[k] = v
                                    if parsed_args:
                                        arguments = json.dumps(parsed_args)
                                    else:
                                        clean_input = re.sub(r'^[\'"]|[\'"]$', '', raw_input)
                                        arguments = json.dumps({first_param: clean_input})
                                else:
                                    # Single raw string -> first parameter
                                    clean_input = re.sub(r'^[\'"]|[\'"]$', '', raw_input)
                                    arguments = json.dumps({first_param: clean_input})

                # Check loop guard before execution
                if self._loop_guard:
                    verdict = self._loop_guard.check_call(
                        parsed["tool"],
                        arguments,
                    )
                    if verdict.blocked:
                        import logging
                        logging.getLogger(__name__).warning(
                            f"Loop guard blocked execution of {parsed['tool']}({arguments}): {verdict.reason}"
                        )
                        tool_result = ToolResult(
                            tool_name=parsed["tool"],
                            content=f"Loop guard: {verdict.reason}",
                            success=False,
                        )
                        all_tool_results.append(tool_result)
                        messages.append(Message(role=Role.USER, content=f"Observation: Loop guard: {verdict.reason}"))
                        continue

                tool_call = ToolCall(
                    id=f"orch_{turns}",
                    name=parsed["tool"],
                    arguments=arguments,
                )
                tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                # Speed optimization: bypass second LLM turn for successful action tools
                if tool_result.success:
                    action_tools = {"shell_exec", "play_music", "play_video", "obsidian_write_note"}
                    if parsed["tool"] in action_tools:
                        app_name = "the application"
                        if parsed["tool"] == "shell_exec":
                            cmd = arguments
                            if "chrome" in cmd.lower():
                                app_name = "Google Chrome"
                            elif "edge" in cmd.lower() or "msedge" in cmd.lower():
                                app_name = "Microsoft Edge"
                            elif "notepad" in cmd.lower():
                                app_name = "Notepad"
                            else:
                                app_name = "the command"
                            content_ans = f"I have successfully executed the request and opened {app_name}, sir."
                        elif parsed["tool"] == "play_music":
                            content_ans = "Right away, sir. I have started the music playback."
                        elif parsed["tool"] == "play_video":
                            content_ans = "Understood. I have queued up the requested video for you, sir."
                        else:
                            content_ans = "I have successfully saved the note in your vault, sir."

                        self._emit_turn_end(turns=turns)
                        return AgentResult(
                            content=content_ans,
                            tool_results=all_tool_results,
                            turns=turns,
                        )

                obs_content = tool_result.content.strip() if tool_result.content else "(tool executed successfully with no output)"

                # After a successful tool call, nudge the model to wrap up
                if tool_result.success:
                    observation = (
                        f"Observation: {obs_content}\n\n"
                        "You have the tool result above. If this answers the user's question, "
                        "respond with FINAL_ANSWER: <your answer>. "
                        "If you need more information, use another tool."
                    )
                else:
                    observation = f"Observation: {obs_content}"

                messages.append(Message(role=Role.USER, content=observation))

                # On the second-to-last turn, force the model to wrap up
                if _turn >= self._max_turns - 2:
                    messages.append(
                        Message(
                            role=Role.USER,
                            content=(
                                "IMPORTANT: This is your last chance to respond. "
                                "You MUST now provide a FINAL_ANSWER based on "
                                "all the information gathered so far. "
                                "Do NOT call any more tools."
                            ),
                        )
                    )
                continue

            # Neither -> treat content as final answer
            self._emit_turn_end(turns=turns)

            import re
            clean_content = content
            clean_content = re.sub(r"^THOUGHT:\s*", "", clean_content, flags=re.IGNORECASE)
            clean_content = re.sub(r"\n*FINAL[_ ]?ANSWER:\s*$", "", clean_content, flags=re.IGNORECASE).strip()

            return AgentResult(
                content=clean_content or "I have finished the task.",
                tool_results=all_tool_results,
                turns=turns,
            )

        # Max turns exceeded — synthesize an answer from tool results
        # instead of the useless "Maximum turns reached" message
        successful_results = [
            tr for tr in all_tool_results if tr.success and tr.content
        ]
        if successful_results:
            # Use the last successful tool result as the basis for the answer
            last_good = successful_results[-1].content.strip()
            # If the last content from the model had useful text, prefer that
            if content and not content.startswith("THOUGHT:"):
                summary = content
            else:
                summary = last_good
            # Still a max-turns exit, even though a usable answer was salvaged
            # from the tool results. Reporting it keeps the flag consistent with
            # the native tool-calling path, so a caller can always tell a
            # converged run from one that simply ran out of turns.
            self._emit_turn_end(turns=turns, max_turns_exceeded=True)
            return AgentResult(
                content=summary,
                tool_results=all_tool_results,
                turns=turns,
                metadata={"max_turns_exceeded": True},
            )

        return self._max_turns_result(all_tool_results, turns)

    @staticmethod
    def _parse_structured_response(text: str) -> dict:
        """Parse THOUGHT/TOOL/INPUT/FINAL_ANSWER from model output."""
        result = {
            "thought": "",
            "tool": "",
            "input": "",
            "final_answer": "",
        }

        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?=\nTOOL:|\nFINAL[_ ]?ANSWER:|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        final_match = re.search(
            r"FINAL[_ ]?ANSWER:\s*(.+)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if final_match:
            result["final_answer"] = final_match.group(1).strip()
            return result

        tool_match = re.search(r"TOOL:\s*(.+)", text, re.IGNORECASE)
        if tool_match:
            result["tool"] = tool_match.group(1).strip()

        input_match = re.search(
            r"INPUT:\s*(.*?)(?=\nTHOUGHT:|\nTOOL:|\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if input_match:
            result["input"] = input_match.group(1).strip()

        return result

    # ------------------------------------------------------------------
    # Function-calling mode (original behaviour)
    # ------------------------------------------------------------------

    def _generate_streaming(
        self,
        messages: list[Message],
        on_delta: Callable[[str], None],
        **extra_kwargs: Any,
    ) -> dict:
        """Like _generate(), but streamed: content goes to `on_delta` as it arrives.

        A tool turn used to be generated whole before any of it reached the
        user, so after a tool ran, voice waited for the model's last word.
        Returns the same shape as engine.generate().
        """
        content_parts: list[str] = []
        calls: list[dict[str, str]] = []
        state: dict[str, Any] = {"usage": {}, "finish_reason": "stop"}

        async def consume() -> None:
            async for chunk in self._engine.stream_full(
                messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                **extra_kwargs,
            ):
                if chunk.content:
                    content_parts.append(chunk.content)
                    on_delta(chunk.content)
                for frag in chunk.tool_calls or []:
                    fn = frag.get("function") or {}
                    # A fragment naming a function starts a call (Ollama sends
                    # whole calls, OpenAI-style streams name only the first
                    # fragment); the rest continue the latest call's arguments.
                    if fn.get("name") or not calls:
                        calls.append({"id": frag.get("id") or f"call_{len(calls)}", "name": fn.get("name") or "", "arguments": ""})
                    calls[-1]["arguments"] += fn.get("arguments") or ""
                if chunk.usage:
                    state["usage"] = dict(chunk.usage)
                if chunk.finish_reason:
                    state["finish_reason"] = chunk.finish_reason

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass  # no loop in this thread: safe to run one
        else:
            return self._generate(messages, **extra_kwargs)

        try:
            asyncio.run(consume())
        except Exception:
            if content_parts or calls:
                raise  # part of the reply already reached the user
            logger.debug("Streaming generate failed; retrying without streaming", exc_info=True)
            return self._generate(messages, **extra_kwargs)

        result: dict[str, Any] = {
            "content": "".join(content_parts),
            "usage": state["usage"],
            "finish_reason": "length" if state["finish_reason"] == "length" else "stop",
        }
        if calls:
            for call in calls:
                call["arguments"] = call["arguments"] or "{}"
            result["tool_calls"] = calls
        return result

    def _run_function_calling(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build initial messages — pass stored system prompt if set
        messages = self._build_messages(
            input, context, system_prompt=self._system_prompt or None
        )

        # Advertise only the tools relevant to this query. The executor
        # still holds every tool, so a call outside the advertised subset
        # continues to execute normally -- this narrows the menu, not the
        # kitchen.
        openai_tools = []
        if self._tools:
            try:
                from orion.tools.tool_router import select_tools

                routed = select_tools(
                    self._tools, input, max_tools=self._max_tools_per_request
                )
                openai_tools = [t.to_openai_function() for t in routed]
            except Exception:
                logger.debug("Tool routing failed; advertising all tools", exc_info=True)
                openai_tools = self._executor.get_openai_tools()

        # Only a routed subset limits which state-changing tools may run.
        # Unknown names are left out: the executor redirects those to
        # propose_new_tool instead of a dead end.
        offered: set[str] = set()
        known: set[str] = set()
        if openai_tools and self._tools and len(openai_tools) < len(self._tools):
            offered = {t.get("function", {}).get("name", "") for t in openai_tools}
            known = {t.spec.name for t in self._tools}

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        started = time.monotonic()

        # Set when every call in a turn was refused or blocked as a repeat: a
        # small model otherwise retried the same blocked call until max_turns
        # and the user got "Maximum turns reached without a final answer."
        force_answer = False

        on_delta = kwargs.get("on_delta")
        stream_turns = callable(on_delta) and _streams_tool_calls(self._engine, self._model)

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Build generate kwargs
            gen_kwargs: dict[str, Any] = {}
            out_of_time = (
                turns > 1
                and self._time_budget_s > 0
                and time.monotonic() - started > self._time_budget_s
            )
            # The final allowed turn answers from what was gathered rather than
            # starting a tool call that could never be followed up.
            last_turn = self._max_turns > 1 and turns == self._max_turns and bool(all_tool_results)
            if out_of_time or force_answer or last_turn:
                # Stop using tools and answer now with what was gathered.
                if out_of_time:
                    reason = "Time limit reached."
                elif force_answer:
                    reason = "Your last tool calls were repeats or not allowed, so they did not run."
                else:
                    reason = "No more tool calls are possible."
                messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            f"({reason} Do not call any more tools. Reply to me now using the "
                            "results above, and say plainly if something is unfinished.)"
                        ),
                    )
                )
            elif openai_tools:
                gen_kwargs["tools"] = openai_tools

            if stream_turns:
                result = self._generate_streaming(messages, on_delta, **gen_kwargs)
            else:
                result = self._generate(messages, **gen_kwargs)

            # Accumulate token usage
            usage = result.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            # No tool calls -> check continuation, then final answer
            if not raw_tool_calls:
                streamed = result.get("content", "") if stream_turns else ""
                content = self._check_continuation(result, messages)
                if stream_turns and len(content) > len(streamed):
                    on_delta(content[len(streamed):])  # continuation after a length cut-off
                content = self._strip_think_tags(content)
                self._emit_turn_end(turns=turns, content_length=len(content))
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                )

            # Build ToolCall objects from raw dicts
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", "{}"),
                )
                for i, tc in enumerate(raw_tool_calls)
            ]

            # Append assistant message with tool calls
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            )

            # Execute each tool (with loop guard check) and append results
            if self._parallel_tools and len(tool_calls) > 1:
                # Parallel execution
                def _exec_tool(tc: ToolCall) -> tuple:
                    refused = _unoffered_call_result(tc.name, offered, known)
                    if refused is not None:
                        return tc, refused
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            return tc, ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                    return tc, self._executor.execute(tc)

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(tool_calls),
                ) as pool:
                    futures = {pool.submit(_exec_tool, tc): tc for tc in tool_calls}
                    results_map: dict[int, tuple] = {}
                    for future in concurrent.futures.as_completed(futures):
                        tc_orig = futures[future]
                        results_map[id(tc_orig)] = future.result()

                # Append results in original order
                for tc in tool_calls:
                    _, tool_result = results_map[id(tc)]
                    all_tool_results.append(tool_result)
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
            else:
                # Sequential execution
                for tc in tool_calls:
                    refused = _unoffered_call_result(tc.name, offered, known)
                    if refused is not None:
                        logger.info("Refused unoffered tool call: %s", tc.name)
                        all_tool_results.append(refused)
                        messages.append(
                            Message(role=Role.TOOL, content=refused.content, tool_call_id=tc.id, name=tc.name)
                        )
                        continue
                    # Loop guard check before execution
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            tool_result = ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                            all_tool_results.append(tool_result)
                            messages.append(
                                Message(
                                    role=Role.TOOL,
                                    content=tool_result.content,
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                )
                            )
                            continue

                    tool_result = self._executor.execute(tc)
                    all_tool_results.append(tool_result)

                    # Append tool response message
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )

            this_turn = all_tool_results[-len(tool_calls):]
            force_answer = bool(this_turn) and all(
                not r.success and r.content.startswith(("Loop guard:", "Not run:")) for r in this_turn
            )

        # Max turns exceeded
        final_content = self._strip_think_tags(content) if content else ""
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=final_content or "Maximum turns reached without a final answer.",
            tool_results=all_tool_results,
            turns=turns,
            metadata={
                "max_turns_exceeded": True,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
        )


__all__ = ["OrchestratorAgent"]
