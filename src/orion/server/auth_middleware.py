"""API key authentication middleware for the Orion server."""

from __future__ import annotations

import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <key>`` on ``/v1/*`` and ``/api/*`` routes.

    Webhook routes and health checks are exempt — they use
    per-channel signature verification instead.
    """

    def __init__(self, app, api_key: str = "") -> None:  # noqa: ANN001
        super().__init__(app)
        self._api_key = api_key or os.environ.get("OPENORION_API_KEY", "")

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if self._api_key and self._requires_auth(request.url.path):
            auth = request.headers.get("Authorization", "")
            if not auth:
                return JSONResponse(
                    {"detail": "Missing Authorization header"},
                    status_code=401,
                )
            scheme, _, token = auth.partition(" ")
            if scheme.lower() != "bearer" or token != self._api_key:
                return JSONResponse(
                    {"detail": "Invalid API key"},
                    status_code=401,
                )
        return await call_next(request)

    @staticmethod
    def _requires_auth(path: str) -> bool:
        """Only protect API routes, not the frontend UI or static assets."""
        return path.startswith("/v1/") or path.startswith("/api/")



def generate_api_key() -> str:
    """Generate a new API key with ``oj_sk_`` prefix."""
    return f"oj_sk_{secrets.token_urlsafe(32)}"


def check_bind_safety(host: str, *, api_key: str) -> None:
    """Refuse to bind non-loopback without an API key.

    Raises ``SystemExit`` if *host* is not a loopback address and
    *api_key* is empty.
    """
    import ipaddress

    try:
        is_loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loop = host in ("localhost", "")

    if not is_loop and not api_key:
        # Refuse, do not merely warn. Orion's tool surface includes
        # shell_exec, file_write, code_interpreter, desktop_control and
        # computer_control, so an unauthenticated non-loopback bind hands
        # full control of this machine to anyone who can reach the port.
        logger.error(
            "Refusing to bind %s without an API key: this would expose "
            "Orion's tools (shell, file write, desktop control) to the "
            "network with no authentication.",
            host,
        )
        raise SystemExit(
            f"Refusing to bind {host} without an API key.\n"
            "Anyone who can reach this port would get unauthenticated "
            "access to shell execution, file writes and desktop control.\n\n"
            "Fix it with either:\n"
            "  orion auth generate-key      # then re-run\n"
            "  orion serve --host 127.0.0.1 # loopback only (default)"
        )

