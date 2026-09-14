"""Escalation notifications for when a desktop toast alone isn't enough.

A desktop toast only reaches the user if they're at their machine. For
emergency-priority messages while the user is away, this also pushes a
direct Telegram message to the user's own bot chat — something they're
far more likely to see from a phone.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def notify_telegram(text: str, *, chat_id: str = "", bot_token: str = "") -> bool:
    """Send *text* directly via the Telegram Bot API, bypassing the agent.

    Uses ``chat_id``/``bot_token`` if given, otherwise falls back to the
    ``TELEGRAM_NOTIFY_CHAT_ID`` / ``TELEGRAM_BOT_TOKEN`` environment
    variables. Returns ``False`` (without raising) if not configured or the
    send fails, since a failed escalation should never crash the caller.
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = chat_id or os.environ.get("TELEGRAM_NOTIFY_CHAT_ID", "")
    if not token or not chat:
        logger.debug("Telegram escalation skipped: not configured")
        return False

    try:
        import httpx

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = httpx.post(url, json={"chat_id": chat, "text": text}, timeout=10.0)
        if resp.status_code >= 300:
            logger.warning(
                "Telegram escalation failed: status %d: %s",
                resp.status_code,
                resp.text,
            )
            return False
        return True
    except Exception:
        logger.debug("Telegram escalation failed", exc_info=True)
        return False


__all__ = ["notify_telegram"]
