"""DiscordChannel — native Discord Bot API adapter."""

from __future__ import annotations

import logging
import os
import threading
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


@ChannelRegistry.register("discord")
class DiscordChannel(BaseChannel):
    """Native Discord channel adapter using the Discord REST API.

    Parameters
    ----------
    bot_token:
        Discord bot token.  Falls back to ``DISCORD_BOT_TOKEN`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "discord"

    def __init__(
        self,
        bot_token: str = "",
        *,
        owner_user_id: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._token = bot_token or os.environ.get("DISCORD_BOT_TOKEN", "")
        self._owner_user_id = str(
            owner_user_id or os.environ.get("DISCORD_OWNER_USER_ID", "")
        ).strip()
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Start listening for incoming messages via discord.py gateway."""
        if not self._token:
            logger.warning("No Discord bot token configured")
            self._status = ChannelStatus.ERROR
            return

        self._stop_event.clear()
        self._status = ChannelStatus.CONNECTING

        try:
            import discord  # noqa: F401

            self._listener_thread = threading.Thread(
                target=self._gateway_loop,
                daemon=True,
            )
            self._listener_thread.start()
            self._status = ChannelStatus.CONNECTED
            logger.info("Discord channel connected (gateway)")
        except ImportError:
            logger.info("discord.py not installed; send-only mode")
            self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        """Stop the listener thread."""
        self._stop_event.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
            self._listener_thread = None
        self._status = ChannelStatus.DISCONNECTED

    # -- send / receive --------------------------------------------------------

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send a message to a Discord channel via REST API."""
        if not self._token:
            logger.warning("Cannot send: no Discord bot token")
            return False

        # `channel` is the channel *type* ("discord") when called from the
        # generic wire_channel() handler, and the real destination is the
        # channel id carried in conversation_id. Posting to /channels/discord/
        # would just 404 -- the same mismatch that silently swallowed every
        # WhatsApp auto-reply until it was tracked down.
        target_channel = conversation_id or channel
        if target_channel == self.channel_id:
            logger.warning("Cannot send: no Discord channel id supplied")
            return False

        try:
            import httpx

            url = f"https://discord.com/api/v10/channels/{target_channel}/messages"
            headers = {
                "Authorization": f"Bot {self._token}",
                "Content-Type": "application/json",
            }
            payload: Dict[str, Any] = {"content": content}

            resp = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code < 300:
                self._publish_sent(target_channel, content, conversation_id)
                return True
            logger.warning(
                "Discord API returned status %d: %s",
                resp.status_code,
                resp.text,
            )
            return False
        except Exception:
            logger.debug("Discord send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["discord"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _gateway_loop(self) -> None:
        """Run the discord.py client in a background thread."""
        try:
            import asyncio

            import discord

            intents = discord.Intents.default()
            intents.message_content = True
            client = discord.Client(intents=intents)

            @client.event
            async def on_message(message):
                if message.author == client.user:
                    return

                # A bot in a server sees every readable message, so record
                # whether this one was actually directed at the owner. The
                # auto-reply policy needs that to avoid answering strangers'
                # conversations in busy channels.
                is_dm = message.guild is None
                mentions_owner = False
                if self._owner_user_id:
                    mentions_owner = any(
                        str(u.id) == self._owner_user_id for u in message.mentions
                    )

                cm = ChannelMessage(
                    channel="discord",
                    sender=str(message.author.id),
                    content=message.content,
                    message_id=str(message.id),
                    conversation_id=str(message.channel.id),
                    metadata={
                        "is_dm": is_dm,
                        "mentions_owner": mentions_owner,
                        "author_name": getattr(message.author, "display_name", "")
                        or str(message.author),
                        "guild_id": str(message.guild.id) if message.guild else "",
                    },
                )
                for handler in self._handlers:
                    try:
                        handler(cm)
                    except Exception:
                        logger.exception("Discord handler error")
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

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(client.start(self._token))
        except Exception:
            logger.debug("Discord gateway loop error", exc_info=True)
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


__all__ = ["DiscordChannel"]
