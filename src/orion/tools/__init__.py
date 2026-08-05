"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

from orion.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# Import built-in tools to trigger @ToolRegistry.register() decorators.
# Each is wrapped in try/except so the package loads even before the
# individual tool modules are created.
try:
    import orion.tools.calculator  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.think  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.retrieval  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.llm_tool  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.file_read  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.web_search  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.code_interpreter  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.code_interpreter_docker  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.repl  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.storage_tools  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.obsidian_search  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.mcp_adapter  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.channel_tools  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.http_request  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.docker_shell_exec  # noqa: F401
    import orion.tools.shell_exec  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.memory_manage  # noqa: F401
except ImportError:
    pass
try:
    import orion.tools.user_profile_manage  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.skill_manage  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.file_write  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.apply_patch  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.git_tool  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.db_query  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.pdf_tool  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.image_tool  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.audio_tool  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.knowledge_tools  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.text_to_speech  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.digest_collect  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.situation_awareness  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.obsidian_write  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.play_music  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.play_video  # noqa: F401
except ImportError:
    pass

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
