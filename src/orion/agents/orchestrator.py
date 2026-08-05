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

import concurrent.futures
import re
from typing import Any, List, Optional

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
        recent_calls: list[str] = []
        turns = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            result = self._generate(messages)
            content = result.get("content", "")

            # DEBUG: Print the content
            print(f"\n[DEBUG_AGENT_CONTENT]\n{content}\n[/DEBUG_AGENT_CONTENT]\n")

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
            self._emit_turn_end(turns=turns)
            return AgentResult(
                content=summary,
                tool_results=all_tool_results,
                turns=turns,
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

        # Get OpenAI-format tool definitions
        openai_tools = self._executor.get_openai_tools() if self._tools else []

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Build generate kwargs
            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            result = self._generate(messages, **gen_kwargs)

            # Accumulate token usage
            usage = result.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            # No tool calls -> check continuation, then final answer
            if not raw_tool_calls:
                content = self._check_continuation(result, messages)
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
