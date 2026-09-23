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
    import orion.tools.browser  # noqa: F401
    import orion.tools.browser_axtree  # noqa: F401
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
    import orion.tools.notion_tools  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.connected_service_tools  # noqa: F401
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

try:
    import orion.tools.vision_capture  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.system_control  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.reminders  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.desktop_control  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.open_app  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.proactive_tools  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.away_mode  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.computer_control  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.system_info  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.tool_forge  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.app_install  # noqa: F401
except ImportError:
    pass

try:
    import orion.tools.game_install  # noqa: F401
except ImportError:
    pass

# Generated tools land here after a user approves propose_new_tool
# (see tool_forge.py / proactive_tools.py's create_tool executor). Each
# file registers itself via the normal @ToolRegistry.register decorator,
# so no further edits to this file are ever needed for future generated
# tools -- only this one-time glob loader.
#
# Gated behind ORION_LOAD_GENERATED_TOOLS (set by cli/serve.py before this
# package is imported) so that AI-authored, approved code only actually
# runs in the real server process it was approved for -- not in every test
# suite, one-off script, or unrelated CLI subcommand that happens to import
# orion.tools (which would otherwise execute each generated tool's
# module-level code too, well past the boundary the rest of this feature's
# approval-gating assumes).
import os as _os

if _os.environ.get("ORION_LOAD_GENERATED_TOOLS") == "1":
    import importlib
    import logging as _logging
    from pathlib import Path as _Path

    _logger = _logging.getLogger(__name__)
    _generated_dir = _Path(__file__).parent / "generated"
    if _generated_dir.is_dir():
        for _py_file in sorted(_generated_dir.glob("*.py")):
            if _py_file.stem.startswith("_"):
                continue
            _module_name = f"orion.tools.generated.{_py_file.stem}"
            try:
                importlib.import_module(_module_name)
            except Exception:
                _logger.exception("Failed to load generated tool module %s", _module_name)

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
