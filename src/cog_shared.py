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

CONTROL_DENIED_MSG = (
    "⛔ Only the **server owner** or members with **Administrator** "
    "permission can control playback."
)


def can_control_playback(bot: Any, member: Any) -> bool:
    """Prosty model uprawnień: właściciel serwera albo administrator.

    Właściciel bota (application owner) też zawsze może — discord.py ustawia
    ``bot.owner_id`` po ``fetch_application_info()``; jeśli jest znany, respektujemy.
    """
    if member is None or getattr(member, "guild", None) is None:
        return False
    if member.guild_permissions.administrator:
        return True
    if member.guild.owner_id == member.id:
        return True
    owner_id = getattr(bot, "owner_id", None)
    if owner_id is not None and member.id == owner_id:
        return True
    return False


async def require_control(bot: Any, ctx: Any) -> bool:
    """Zwraca True gdy autor może kontrolować; inaczej wysyła odmowę i False."""
    if can_control_playback(bot, getattr(ctx, "author", None)):
        return True
    try:
        await ctx.send(CONTROL_DENIED_MSG)
    except Exception:  # noqa: BLE001
        pass
    return False


class PlaybackCtx:
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
