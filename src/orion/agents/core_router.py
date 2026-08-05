"""CoreRouterAgent — multiplexer that delegates to specialized sub-agents."""

import json
import logging
import re
from typing import Any, Optional

from orion.agents._stubs import AgentContext, AgentResult, BaseAgent
from orion.agents.orchestrator import OrchestratorAgent
from orion.core.events import EventBus
from orion.core.registry import AgentRegistry, ToolRegistry
from orion.core.types import Message, Role
from orion.engine._stubs import InferenceEngine

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

# Domain definitions for the router
DOMAINS = {
    "coding": {
        "description": "Software engineering, debugging, code generation, git operations.",
        "tools": ["shell_exec", "file_read", "file_write", "git_tool", "repl", "apply_patch"],
        "prompt": "You are a specialized Coding & Development Agent. Focus on providing clean, secure, and efficient code. Use your tools to navigate the codebase, read files, execute shell commands, and apply patches. When modifying files, always ensure tests pass."
    },
    "cybersecurity": {
        "description": "Vulnerability scanning, code review for security, system monitoring.",
        "tools": ["scan_chunks", "shell_exec", "web_search"],
        "prompt": "You are a specialized Cybersecurity Agent. Focus on identifying vulnerabilities, auditing code, and analyzing system security. Use your scanning and execution tools to verify security postures."
    },
    "marketing": {
        "description": "Content creation, SEO, social media, copywriting.",
        "tools": ["web_search", "file_write", "image_tool"],
        "prompt": "You are a specialized Marketing & Content Agent. Focus on writing engaging copy, planning social media strategy, and optimizing for SEO. Use web search for market research."
    },
    "analytics": {
        "description": "Database querying, running data visualization scripts, statistical analysis.",
        "tools": ["db_query", "code_interpreter"],
        "prompt": "You are a specialized Data Analytics Agent. Focus on querying databases, performing statistical analysis, and generating insights using Python data science libraries."
    },
    "workspace": {
        "description": "Managing notes (Obsidian), reading emails, calendar scheduling.",
        "tools": ["obsidian_search", "obsidian_write", "memory_manage"],
        "prompt": "You are a specialized Workspace & Productivity Agent. Focus on personal knowledge management, note-taking, and organizing the user's workspace. You have direct access to their notes vault."
    },
    "system": {
        "description": "Managing docker containers, local system configuration, DevOps.",
        "tools": ["docker_shell_exec", "shell_exec"],
        "prompt": "You are a specialized System & DevOps Agent. Focus on managing containers, configuring local environments, and executing system administration tasks safely."
    },
    "research": {
        "description": "Deep web search, academic research, PDF analysis, information synthesis.",
        "tools": ["web_search", "pdf_tool", "knowledge_search"],
        "prompt": "You are a specialized Research Agent. Focus on synthesizing information from deep web searches and academic papers. Provide detailed, well-cited answers."
    },
    "general": {
        "description": "Everyday chatting, quick QA, standard web search without a specific domain.",
        "tools": ["web_search", "calculator", "play_music", "play_video"],
        "prompt": "You are a helpful General Assistant. Provide friendly and concise answers. If a question is complex, answer it to the best of your ability."
    }
}

_ROUTER_PROMPT = """You are the Core Router for a multi-agent system.
Your job is to analyze the user's request and classify it into exactly one of the following domains:

{domain_descriptions}

Respond ONLY with a valid JSON object in this format:
{{"domain": "<domain_name>"}}

Do not include any other text or markdown formatting.
"""

@AgentRegistry.register("core_router")
class CoreRouterAgent(BaseAgent):
    """An agent that routes requests to specialized sub-agents based on intent classification."""

    agent_id = "core_router"

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        interactive: bool = False,
        confirm_callback=None,
        **kwargs: Any
    ) -> None:
        super().__init__(engine, model, bus=bus)
        self._interactive = interactive
        self._confirm_callback = confirm_callback

    @traceable(name="CoreRouterAgent.run", run_type="chain")
    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any
    ) -> AgentResult:

        self._emit_turn_start(input)

        # 1. Build the domain descriptions for the prompt
        desc_lines = []
        for d, info in DOMAINS.items():
            desc_lines.append(f"- {d}: {info['description']}")

        system_prompt = _ROUTER_PROMPT.format(domain_descriptions="\n".join(desc_lines))

        messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=f"Request to classify: {input}")
        ]

        # 2. Call the engine for classification (use temperature 0 for deterministic routing)
        try:
            logger.info("Routing request...")
            result = self._engine.generate(
                messages,
                model=self._model,
                temperature=0.0,
                max_tokens=20
            )
            content = result.get("content", "").strip()

            # Clean up markdown if the LLM didn't listen
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()

            # Attempt to extract json from text if it's embedded
            match = re.search(r'\{[^{}]*\}', content)
            if match:
                content = match.group(0)

            parsed = json.loads(content)
            selected_domain = parsed.get("domain", "general").lower()
            if selected_domain not in DOMAINS:
                selected_domain = "general"
        except Exception as e:
            logger.warning(f"Failed to parse router decision, falling back to general. Error: {e}")
            selected_domain = "general"

        logger.info(f"Routed to domain: {selected_domain}")

        # 3. Instantiate the target sub-agent
        domain_config = DOMAINS[selected_domain]

        # Resolve tools
        tools = []
        for tool_name in domain_config["tools"]:
            if ToolRegistry.contains(tool_name):
                try:
                    tools.append(ToolRegistry.create(tool_name))
                except Exception as e:
                    logger.warning(f"Failed to instantiate tool {tool_name} for domain {selected_domain}: {e}")

        # Create the sub-agent
        sub_agent = OrchestratorAgent(
            engine=self._engine,
            model=self._model,
            tools=tools,
            bus=self._bus,
            system_prompt=domain_config["prompt"],
            interactive=self._interactive,
            confirm_callback=self._confirm_callback,
            max_turns=kwargs.get("max_turns", 10),
            temperature=kwargs.get("temperature", 0.7)
        )

        # 4. Delegate the run to the sub-agent
        sub_result = sub_agent.run(input, context=context, **kwargs)

        self._emit_turn_end(turns=1 + sub_result.turns)

        # Prepend a small note indicating the sub-agent that handled it
        enhanced_content = f"*[Routed to {selected_domain.title()} Agent]*\n\n{sub_result.content}"
        sub_result.content = enhanced_content

        return sub_result
