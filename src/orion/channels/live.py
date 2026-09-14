"""Registry of connected, live channel instances.

Some channels are stateless: a :class:`TelegramChannel` constructed on the
spot can send immediately, because sending is just an HTTPS call carrying a
bot token. Others hold a live connection -- ``WhatsAppBaileysChannel`` owns a
Node bridge subprocess and an authenticated WhatsApp session -- and a freshly
constructed instance of one of those can do nothing at all.

Outbound sends used to always construct a new instance, which meant an
approved WhatsApp message failed with "bridge not connected". Worse, making
that instance connect on demand would start a *second* bridge against the same
auth, and WhatsApp permits only one session per linked device: the two
connections then evict each other in a loop and inbound messages stop
arriving entirely.

So the process registers its connected channels here at startup, and senders
look for a live instance before falling back to constructing one.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LIVE_CHANNELS: Dict[str, Any] = {}

# Names callers use -> canonical registry keys. The agent is told to say
# "whatsapp", while the channel registry key is "whatsapp_baileys".
_ALIASES = {
    "whatsapp": "whatsapp_baileys",
    "whatsapp_baileys": "whatsapp_baileys",
    "telegram": "telegram",
    "discord": "discord",
    "slack": "slack",
}


def canonical_key(name: str) -> str:
    key = (name or "").strip().lower()
    return _ALIASES.get(key, key)


def register_live_channel(name: str, channel: Any) -> None:
    """Record *channel* as the process's connected instance for *name*."""
    key = canonical_key(name)
    if not key or channel is None:
        return
    with _LOCK:
        _LIVE_CHANNELS[key] = channel
    logger.info("Registered live channel: %s", key)


def get_live_channel(name: str) -> Optional[Any]:
    """Return the connected instance for *name*, if one was registered."""
    with _LOCK:
        return _LIVE_CHANNELS.get(canonical_key(name))


def clear_live_channels() -> None:
    with _LOCK:
        _LIVE_CHANNELS.clear()


__all__ = [
    "canonical_key",
    "register_live_channel",
    "get_live_channel",
    "clear_live_channels",
]
