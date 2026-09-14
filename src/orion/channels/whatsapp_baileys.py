"""WhatsAppBaileysChannel -- bidirectional WhatsApp messaging via Baileys protocol.

Spawns a Node.js subprocess that runs the Baileys bridge (JSON-line protocol
on stdio).  The bridge handles QR-code authentication, message sending, and
incoming-message forwarding.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from orion.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from orion.core.events import EventBus, EventType
from orion.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)

# Dedicated always-on file log for the bridge.
#
# The bridge's diagnostics are the only way to tell "WhatsApp closed our
# socket" apart from "the socket is fine but nothing was delivered", and the
# desktop app spawns the backend with stdout piped to null -- so routing them
# through the normal logger at DEBUG level makes them invisible in exactly
# the situation where they matter. Write them to a known file instead.
_BRIDGE_LOG_PATH = Path.home() / ".orion" / "whatsapp_bridge.log"


def _bridge_log(message: str) -> None:
    """Append a timestamped line to the bridge log, best-effort."""
    try:
        import time

        _BRIDGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Keep one previous log; a reconnect storm once grew this to 190k lines.
        if _BRIDGE_LOG_PATH.exists() and _BRIDGE_LOG_PATH.stat().st_size > 5_000_000:
            _BRIDGE_LOG_PATH.replace(_BRIDGE_LOG_PATH.with_suffix(".log.1"))
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with _BRIDGE_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except Exception:
        pass  # logging must never break the channel


# Path to the bundled bridge shipped inside the package.
# In editable installs this lives next to this file; in wheel installs
# it is placed under _node_modules/ to avoid namespace package conflicts.
_BRIDGE_SRC = Path(__file__).resolve().parent / "whatsapp_baileys_bridge"
if not _BRIDGE_SRC.exists():
    _BRIDGE_SRC = (
        Path(__file__).resolve().parents[2]
        / "_node_modules"
        / "whatsapp_baileys_bridge"
    )

# Default runtime directory (npm install + auth state).
_DEFAULT_RUNTIME_DIR = Path.home() / ".orion" / "whatsapp_baileys_bridge"


@ChannelRegistry.register("whatsapp_baileys")
class WhatsAppBaileysChannel(BaseChannel):
    """Bidirectional WhatsApp channel using the Baileys protocol.

    Communicates with a Node.js bridge subprocess over JSON-line stdio.

    Parameters
    ----------
    auth_dir:
        Directory for Baileys auth state persistence.  Defaults to
        ``~/.orion/whatsapp_baileys_bridge/auth``.
    assistant_name:
        Display name used by the assistant in conversations.
    assistant_has_own_number:
        If ``True`` the assistant has a dedicated WhatsApp number and will
        not filter out its own messages.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "whatsapp_baileys"

    def __init__(
        self,
        *,
        auth_dir: str = "",
        assistant_name: str = "Orion",
        assistant_has_own_number: bool = False,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._auth_dir = auth_dir
        self._assistant_name = assistant_name
        self._assistant_has_own_number = assistant_has_own_number
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._runtime_dir = _DEFAULT_RUNTIME_DIR
        self._last_qr: str = ""
        # Set when WhatsApp reports this device was logged out: the saved
        # session is dead, so the next connect() must start a fresh pairing.
        self._logged_out = False
        # Last time the owner sent a message in a given conversation from
        # their own phone/linked device (not through Orion). Lets callers
        # cancel a pending auto-reply once the owner has visibly replied
        # themselves -- see owner_replied_since().
        self._own_message_at: Dict[str, float] = {}

    # -- bridge lifecycle -------------------------------------------------------

    def _ensure_bridge(self) -> Path:
        """Copy bundled bridge to runtime dir and run ``npm install`` if needed.

        Returns the path to ``dist/bridge.js``.

        Raises
        ------
        RuntimeError
            If ``node`` is not found on ``PATH``.
        """
        if shutil.which("node") is None:
            raise RuntimeError(
                "Node.js is required for WhatsAppBaileysChannel but 'node' "
                "was not found on PATH.  Install Node.js 22+ and try again."
            )

        runtime = self._runtime_dir
        runtime.mkdir(parents=True, exist_ok=True)

        # Copy package.json + dist/ from bundled source if not already present,
        # or if the bundled version is newer.
        pkg_dst = runtime / "package.json"
        pkg_src = _BRIDGE_SRC / "package.json"
        pkg_updated = pkg_src.exists() and (
            not pkg_dst.exists() or pkg_src.stat().st_mtime > pkg_dst.stat().st_mtime
        )
        if pkg_updated:
            shutil.copy2(pkg_src, pkg_dst)

        dist_dst = runtime / "dist"
        dist_src = _BRIDGE_SRC / "dist"
        if dist_src.exists():
            if dist_dst.exists():
                shutil.rmtree(dist_dst)
            shutil.copytree(dist_src, dist_dst)

        # Run npm install if node_modules is missing, or if package.json just
        # changed (e.g. a dependency version bump) — otherwise a stale
        # node_modules silently keeps running the old dependency version.
        node_modules = runtime / "node_modules"
        if pkg_updated and node_modules.exists():
            shutil.rmtree(node_modules)
        if not node_modules.exists():
            # On Windows, npm resolves to npm.cmd — subprocess.run can't find
            # it via plain "npm" without shutil.which resolving the exact
            # executable first (a real failure observed here: FileNotFoundError).
            npm_bin = shutil.which("npm")
            if npm_bin is None:
                raise RuntimeError(
                    "npm is required to set up the WhatsApp bridge but was not found on PATH."
                )
            logger.info("Running npm install in %s", runtime)
            subprocess.run(
                [npm_bin, "install", "--production"],
                cwd=str(runtime),
                check=True,
                capture_output=True,
            )

        bridge_js = runtime / "dist" / "bridge.js"
        if not bridge_js.exists():
            raise RuntimeError(
                f"Bridge entry point not found at {bridge_js}.  "
                "Ensure the bridge TypeScript has been compiled."
            )
        return bridge_js

    # -- BaseChannel interface ---------------------------------------------------

    def connect(self) -> None:
        """Spawn the Node.js bridge subprocess and start the reader thread."""
        if self._status == ChannelStatus.CONNECTED:
            return
        proc = self._process
        if proc is not None and proc.poll() is None:
            if not self._logged_out:
                # The bridge is alive and retrying on its own. Starting a
                # second one on the same session made the two knock each other
                # offline -- the "click Connect every time" loop.
                return
            self._retire_logged_out_session(proc)

        self._status = ChannelStatus.CONNECTING

        try:
            bridge_js = self._ensure_bridge()
        except RuntimeError as exc:
            logger.error("Bridge setup failed: %s", exc)
            self._status = ChannelStatus.ERROR
            return

        auth = self._auth_dir or str(self._runtime_dir / "auth")
        self._stop_orphaned_bridge()

        try:
            self._stop_event.clear()
            self._process = subprocess.Popen(
                ["node", str(bridge_js), "--auth-dir", auth],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                # Windows defaults text mode to the ANSI code page (cp1252),
                # but the bridge emits UTF-8: WhatsApp traffic routinely
                # carries emoji and non-Latin script. Decoding those as cp1252
                # raised UnicodeDecodeError inside the reader thread, killing
                # it outright -- the process stayed alive and "connected"
                # while silently receiving nothing further. errors="replace"
                # means a stray undecodable byte can never take the channel
                # down again.
                encoding="utf-8",
                errors="replace",
            )
            self._write_pid_file(self._process.pid)
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
            )
            self._reader_thread.start()

            # The bridge logs verbosely to stderr for debugging. If nobody
            # drains subprocess.PIPE, the OS pipe buffer fills up and the
            # child blocks on its next stderr write -- freezing the whole
            # (single-threaded) Node process before it can emit anything on
            # stdout, including the QR code. Drain it here instead.
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                daemon=True,
            )
            self._stderr_thread.start()

            # Make sure the bridge dies with us on any orderly exit. Without
            # this, nothing calls disconnect() when the backend goes away and
            # the bridge lingers holding the single WhatsApp session, which
            # then fights the next backend's bridge.
            self._register_exit_cleanup()

            logger.info(
                "WhatsApp Baileys bridge started (pid=%s)",
                self._process.pid,
            )
            _bridge_log(f"BRIDGE-STARTED pid={self._process.pid}")
        except Exception:
            logger.exception("Failed to start bridge subprocess")
            self._status = ChannelStatus.ERROR

    @property
    def _pid_file(self) -> Path:
        return self._runtime_dir / "bridge.pid"

    def _write_pid_file(self, pid: int) -> None:
        try:
            self._pid_file.write_text(str(pid), encoding="utf-8")
        except OSError:
            logger.debug("Could not write bridge pid file", exc_info=True)

    def _stop_orphaned_bridge(self) -> None:
        """Stop a bridge left running by a previous backend.

        A backend that is killed (not shut down cleanly) never runs its exit
        hook, so its bridge keeps the WhatsApp session open. The next backend's
        bridge then competes for the same session and each knocks the other
        offline -- which is why WhatsApp needed "Connect" after every restart.
        """
        try:
            pid = int(self._pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        if self._process is not None and self._process.pid == pid:
            return
        try:
            import psutil

            proc = psutil.Process(pid)
            cmdline = " ".join(proc.cmdline())
        except Exception:
            return  # already gone, or not ours to inspect
        if "bridge.js" not in cmdline or str(self._runtime_dir) not in cmdline:
            return  # the pid was reused by an unrelated process
        _bridge_log(f"ORPHAN-BRIDGE stopping pid={pid} left by a previous backend")
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _retire_logged_out_session(self, proc: subprocess.Popen) -> None:
        """Stop a bridge whose session was logged out and set its auth aside."""
        try:
            proc.terminate()
            proc.wait(timeout=5.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._process = None
        auth = Path(self._auth_dir or str(self._runtime_dir / "auth"))
        if auth.exists():
            # Kept, not deleted: renamed so a fresh pairing starts clean.
            auth.rename(auth.with_name(f"{auth.name}.logged-out-{int(time.time())}"))
        self._logged_out = False
        _bridge_log("LOGGED-OUT session retired; starting fresh pairing")

    def _register_exit_cleanup(self) -> None:
        """Terminate the bridge on interpreter exit and on SIGINT/SIGTERM."""
        if getattr(self, "_exit_hook_registered", False):
            return
        self._exit_hook_registered = True

        import atexit
        import signal

        atexit.register(self._cleanup_on_exit)

        def _handler(signum, _frame):
            self._cleanup_on_exit()
            # Restore default handling so the process still terminates as the
            # signal intended rather than being silently swallowed here.
            try:
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
            except Exception:
                raise SystemExit(0)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass  # not on the main thread, or unsupported on this platform

    def _cleanup_on_exit(self) -> None:
        proc = self._process
        if proc is None or proc.poll() is not None:
            return
        _bridge_log(f"EXIT-CLEANUP terminating bridge pid={proc.pid}")
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def disconnect(self) -> None:
        """Send disconnect command to the bridge and terminate the subprocess."""
        self._stop_event.set()

        if self._process is not None and self._process.stdin is not None:
            try:
                self._write_command({"type": "disconnect"})
            except Exception:
                logger.debug("Could not send disconnect command", exc_info=True)

        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5.0)
            except Exception:
                logger.debug("Bridge process termination error", exc_info=True)
            self._process = None

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5.0)
            self._reader_thread = None

        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=5.0)
            self._stderr_thread = None

        self._status = ChannelStatus.DISCONNECTED

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send a message to a WhatsApp JID via the bridge subprocess."""
        if self._process is None or self._status != ChannelStatus.CONNECTED:
            logger.warning("Cannot send: bridge not connected")
            _bridge_log(
                f"SEND-BLOCKED status={self._status} "
                f"proc={'yes' if self._process else 'none'} "
                f"conversation_id={conversation_id!r}"
            )
            return False

        # `channel` is the channel *type* (e.g. "whatsapp_baileys") when called
        # from the generic wire_channel() handler -- the actual WhatsApp JID
        # to reply to is only ever available as conversation_id (it's what
        # _handle_bridge_event set as ChannelMessage.conversation_id from the
        # inbound event's "jid" field). Falling back to `channel` keeps this
        # usable for direct channel="<jid>" callers too.
        jid = conversation_id or channel

        try:
            self._write_command(
                {
                    "type": "send",
                    "jid": jid,
                    "text": content,
                }
            )
            _bridge_log(f"SEND-OK jid={jid!r} text={content[:60]!r}")
            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception as exc:
            logger.debug("WhatsApp Baileys send failed", exc_info=True)
            _bridge_log(f"SEND-FAILED jid={jid!r} {exc!r}")
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["whatsapp_baileys"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    @property
    def qr_code(self) -> str:
        """The most recent QR pairing string from the bridge, or "" if
        none is pending (already linked, or connect() hasn't been called).
        Empty is the honest default -- never a stale or placeholder code.
        """
        return self._last_qr

    def owner_replied_since(self, conversation_id: str, since_ts: float) -> bool:
        """Whether the owner has sent a message in *conversation_id* (from
        their own phone or any other linked device, not through Orion)
        after *since_ts*.

        Used to cancel a pending auto-reply once the owner has visibly
        replied themselves -- generating a reply can take a minute or more
        on a local model, plenty of time for the owner to see the message
        on their phone and answer it in person.
        """
        return self._own_message_at.get(conversation_id, 0.0) > since_ts

    # -- internal helpers -------------------------------------------------------

    def _write_command(self, cmd: Dict[str, Any]) -> None:
        """Write a JSON-line command to the bridge's stdin."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Bridge process not running")
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _reader_loop(self) -> None:
        """Background thread: read JSON lines from bridge stdout."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        try:
            for raw_line in proc.stdout:
                if self._stop_event.is_set():
                    break

                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON line from bridge: %s", line)
                    _bridge_log(f"STDOUT-NONJSON {line}")
                    continue

                _bridge_log(f"EVENT {line}")
                self._handle_bridge_event(event)
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.debug("Reader loop error", exc_info=True)
                _bridge_log(f"READER-LOOP-DIED {exc!r}")
                self._status = ChannelStatus.ERROR
        else:
            _bridge_log("READER-LOOP-EOF (bridge stdout closed)")

    def _stderr_loop(self) -> None:
        """Background thread: drain bridge stderr so it never blocks the child."""
        proc = self._process
        if proc is None or proc.stderr is None:
            return

        try:
            for raw_line in proc.stderr:
                if self._stop_event.is_set():
                    break
                line = raw_line.strip()
                if line:
                    logger.debug("WhatsApp bridge stderr: %s", line)
                    _bridge_log(f"STDERR {line}")
        except Exception:
            if not self._stop_event.is_set():
                logger.debug("Stderr loop error", exc_info=True)
                _bridge_log("STDERR-LOOP-DIED")

    def _handle_bridge_event(self, event: Dict[str, Any]) -> None:
        """Dispatch a single JSON event from the bridge."""
        event_type = event.get("type", "")

        if event_type == "status":
            new_status = event.get("status", "")
            if new_status == "connected":
                self._status = ChannelStatus.CONNECTED
                self._logged_out = False
                self._last_qr = ""  # stale once linked -- don't keep showing an old code
                logger.info("WhatsApp Baileys bridge connected")
            elif new_status == "reconnecting":
                # Transient drop; the bridge retries by itself with backoff.
                self._status = ChannelStatus.CONNECTING
            elif new_status == "disconnected":
                self._status = ChannelStatus.DISCONNECTED

        elif event_type == "qr":
            self._last_qr = event.get("data", "")
            logger.info("WhatsApp QR code received -- scan to authenticate")

        elif event_type == "message":
            cm = ChannelMessage(
                channel="whatsapp_baileys",
                sender=event.get("sender", ""),
                content=event.get("text", ""),
                message_id=event.get("message_id", ""),
                conversation_id=event.get("jid", ""),
            )
            _bridge_log(
                f"INBOUND jid={cm.conversation_id!r} sender={cm.sender!r} "
                f"handlers={len(self._handlers)} text={cm.content[:60]!r}"
            )
            for handler in self._handlers:
                try:
                    handler(cm)
                except Exception as exc:
                    logger.exception("WhatsApp Baileys handler error")
                    _bridge_log(f"HANDLER-ERROR {exc!r}")
            if self._bus is not None:
                self._bus.publish(
                    EventType.CHANNEL_MESSAGE_RECEIVED,
                    {
                        "channel": cm.channel,
                        "sender": cm.sender,
                        "content": cm.content,
                        "message_id": cm.message_id,
                    },
                )

        elif event_type == "own_message":
            jid = event.get("jid", "")
            if jid:
                self._own_message_at[jid] = time.time()

        elif event_type == "error":
            message = event.get("message", "unknown")
            logger.error("Bridge error: %s", message)
            if "logged out" in str(message).lower():
                self._logged_out = True
            self._status = ChannelStatus.ERROR

    def _publish_sent(self, channel: str, content: str, conversation_id: str) -> None:
        """Publish a CHANNEL_MESSAGE_SENT event on the bus."""
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": channel,
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )


__all__ = ["WhatsAppBaileysChannel"]
