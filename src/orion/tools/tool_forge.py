"""propose_new_tool — the agent drafts a brand-new tool's source code and
queues it for the user's explicit approval before it is ever registered.

Reuses the existing queue_action / execute_pending_actions / ApprovalStore
lifecycle (proactive_tools.py) rather than inventing a second approval
mechanism -- creating a tool is treated as exactly the kind of high-tier,
irreversible action that flow already exists for (see queue_action's tier
semantics). Nothing here writes to disk, touches the registry, or EXECUTES
the proposed code -- validation at proposal time is pure AST inspection
(_static_validate), no exec() involved. The one thing that does run the
code, _sandbox_smoke_test, is only ever called from
proactive_tools.py's execute_pending_actions "create_tool" branch, after a
real human "yes" -- never from this tool's own execute(). That ordering is
the actual safety boundary: nothing the model proposes runs on the user's
machine before they've approved it.

Honesty note on the smoke test: it runs in an isolated OS subprocess with
a timeout -- the same isolation level the existing (non-Docker)
code_interpreter tool already relies on, not a network/filesystem-
restricted container. A true container sandbox would need the orion
package installed inside the image to even import BaseTool, which isn't
set up yet. This is disclosed to the user in the create_tool executor's
result message rather than silently overclaiming Docker-grade isolation.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Tuple

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec
from orion.tools.approval_store import TIER_HIGH
from orion.tools.proactive_tools import get_store

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

GENERATED_DIR = Path(__file__).parent / "generated"

_CAPABILITY_HINTS = {
    "file:write": (".write_text(", ".write_bytes(", "open(", "shutil.copy", "shutil.move"),
    "file:read": ("open(", ".read_text(", ".read_bytes(", "Path("),
    "code:execute": ("subprocess.", "os.system(", "os.popen(", "eval(", "exec("),
    "network:fetch": ("requests.", "httpx.", "urllib.", "socket.", "aiohttp."),
}


def _infer_capabilities(source: str) -> List[str]:
    """Best-effort capability tagging from what the generated code actually
    touches, so it goes through the same RBAC gate as every built-in tool
    (see security/capabilities.py) rather than getting a free pass."""
    caps = set()
    for cap, needles in _CAPABILITY_HINTS.items():
        if any(n in source for n in needles):
            caps.add(cap)
    return sorted(caps)


def _static_validate(name: str, source: str) -> Tuple[bool, str]:
    """Pure AST inspection -- no execution at all. Confirms the module has
    the same shape every existing tool already has before anything runs."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"

    class_def = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            base_names = [
                b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                for b in node.bases
            ]
            if "BaseTool" in base_names:
                class_def = node
                break
    if class_def is None:
        return False, "No class subclassing BaseTool was found."

    method_names = {
        n.name for n in class_def.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    prop_names = {
        n.name
        for n in class_def.body
        if isinstance(n, ast.FunctionDef)
        and any(isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list)
    }
    if "spec" not in prop_names:
        return False, "Class is missing a `spec` property."
    if "execute" not in method_names:
        return False, "Class is missing an `execute` method."

    registered_ok = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "register" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and arg.value == name:
                    registered_ok = True
    if not registered_ok:
        return False, f'Missing `@ToolRegistry.register("{name}")` matching the given name.'

    return True, "ok"


def _sandbox_smoke_test(source: str) -> Tuple[bool, str]:
    """Confirm the module actually imports and the tool class can be
    instantiated, in an isolated subprocess with a hard timeout.

    Only ever call this AFTER the user has approved the tool (see the
    module docstring) -- this is the one place the candidate code actually
    runs.
    """
    probe = (
        "import sys, types\n"
        "with open(sys.argv[1], 'r', encoding='utf-8') as f:\n"
        "    src = f.read()\n"
        "mod = types.ModuleType('generated_probe')\n"
        "try:\n"
        "    exec(compile(src, '<generated>', 'exec'), mod.__dict__)\n"
        "except Exception as exc:\n"
        "    print('IMPORT_ERROR:', exc); sys.exit(1)\n"
        "from orion.tools._stubs import BaseTool\n"
        "cls = None\n"
        "for v in vars(mod).values():\n"
        "    if isinstance(v, type) and issubclass(v, BaseTool) and v is not BaseTool:\n"
        "        cls = v; break\n"
        "if cls is None:\n"
        "    print('NO_TOOL_CLASS'); sys.exit(1)\n"
        "try:\n"
        "    inst = cls()\n"
        "    s = inst.spec\n"
        "    print('OK', s.name)\n"
        "except Exception as exc:\n"
        "    print('INSTANTIATE_ERROR:', exc); sys.exit(1)\n"
    )
    # The candidate source is written to a temp file and passed as a path,
    # not embedded in a -c command-line string -- a "complete,
    # self-contained" generated module can be large, and Windows'
    # CreateProcess caps a process's whole command line around 32K chars;
    # repr()-escaping the source for a -c string could exceed that for a
    # large tool and fail with an OS-level error instead of a clean result.
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = Path(tmpdir) / "candidate.py"
        src_path.write_text(source, encoding="utf-8")
        probe_path = Path(tmpdir) / "probe.py"
        probe_path.write_text(probe, encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(probe_path), str(src_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return False, "Smoke test timed out after 15s."
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0 and "OK" in output:
        return True, output.strip()
    return False, output.strip() or f"Exited with code {result.returncode}"


@ToolRegistry.register("propose_new_tool")
class ProposeNewToolTool(BaseTool):
    """Draft a brand-new tool and queue it for the user's explicit approval."""

    tool_id = "propose_new_tool"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="propose_new_tool",
            description=(
                "Propose a brand-new tool when none of your existing tools cover what the "
                "user asked for. Write a complete, self-contained Python module implementing "
                "one class that subclasses BaseTool (import from orion.tools._stubs), with a "
                "`spec` property returning a ToolSpec and an `execute(self, **params)` method "
                "returning a ToolResult (import from orion.core.types). Decorate the class with "
                '@ToolRegistry.register("<name>") using the exact same name you pass here '
                "(import ToolRegistry from orion.core.registry) -- copy the shape of any "
                "existing tool file if unsure. This does NOT create the tool immediately -- it "
                "is validated, smoke-tested, then queued for the user's explicit yes/no exactly "
                "like queue_action. Never claim the tool exists or is usable until you see it "
                "actually approved AND the backend has restarted -- a new tool cannot be called "
                "in the same turn it was proposed in."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "snake_case tool name, e.g. 'currency_convert'.",
                    },
                    "description": {
                        "type": "string",
                        "description": "One sentence: what this tool does and why it's needed.",
                    },
                    "implementation_code": {
                        "type": "string",
                        "description": "Full Python source for the new tool module.",
                    },
                },
                "required": ["name", "description", "implementation_code"],
            },
            category="proactive",
        )

    def execute(self, **params: Any) -> ToolResult:
        name = (params.get("name") or "").strip()
        description = params.get("description", "")
        source = params.get("implementation_code", "")

        if not _NAME_RE.match(name):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Invalid tool name {name!r} -- must be snake_case, e.g. 'currency_convert'.",
            )
        if ToolRegistry.contains(name):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"A tool named '{name}' already exists.",
            )
        if (GENERATED_DIR / f"{name}.py").exists():
            # Caught separately from the registry check above: a previously
            # approved-but-not-yet-restarted-into tool sits on disk without
            # being in this process's ToolRegistry yet. Reject cleanly here
            # rather than letting it reach the smoke test -- that subprocess
            # imports orion.tools._stubs, which runs the tools package's
            # __init__.py, which glob-loads generated/*.py, so it would
            # otherwise collide with the freshly exec'd duplicate mid
            # registration and fail with a confusing crash instead of a
            # clear message.
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    f"A generated tool named '{name}' already exists on disk "
                    "(approved earlier, awaiting restart, or never cleaned up). "
                    "Choose a different name, or remove the existing one first."
                ),
            )

        ok, reason = _static_validate(name, source)
        if not ok:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Rejected before review: {reason}",
            )

        # No execution happens here -- only pure AST inspection above. The
        # candidate code is not run (smoke-tested) until after the user
        # approves it, in proactive_tools.py's create_tool executor. That
        # ordering, not this validation, is what makes "nothing runs before
        # approval" true.
        capabilities = _infer_capabilities(source)

        store = get_store()
        action = store.queue_action(
            action_type="create_tool",
            description=f"Add new tool '{name}': {description}",
            payload={
                "name": name,
                "description": description,
                "implementation_code": source,
                "inferred_capabilities": capabilities,
                "isolation_note": (
                    "Will be smoke-tested in an isolated OS process with a 15s "
                    "timeout at approval time -- not a network/filesystem-"
                    "restricted container, and not run before that. This proves "
                    "the code runs, not that it's safe or correct for its stated "
                    "purpose."
                ),
            },
            permission_key=f"create_tool:{name}",
            tier=TIER_HIGH,
        )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=(
                f"Queued for your approval as action {action.id}. It has not "
                "run anywhere yet -- it will be smoke-tested only once "
                f"approved. Reply 'yes {action.id}' to add it, or "
                f"'no {action.id}' to discard it. It will need a backend "
                "restart to actually become callable, which happens "
                "automatically on approval."
            ),
            metadata={"action_id": action.id},
        )


__all__ = ["ProposeNewToolTool", "GENERATED_DIR"]
