"""Shared helpers for Discord command cogs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .discord_compat import discord

if TYPE_CHECKING:
    import discord
    from discord import Guild, Member, VoiceClient

logger = logging.getLogger(__name__)
FAVORITE_EMOJI = "⭐"


class FakeContext:
    """Minimal context stand-in for auto-start/reconnect flows.

    Provides enough of the ``discord.ext.commands.Context`` interface
    (``guild``, ``author``, ``voice_client``, ``send``) to be passed
    into cog methods that expect a real command context.
    """

    def __init__(
        self,
        guild: Guild,
        author: Member,
        voice_client: VoiceClient | None,
        send: Any = None,
    ) -> None:
        self.guild = guild
        self.author = author
        self.voice_client = voice_client
        self._send = send

    async def send(self, *args: Any, **kwargs: Any) -> discord.Message | None:
        if self._send is None:
            return None
        return await self._send(*args, **kwargs)
