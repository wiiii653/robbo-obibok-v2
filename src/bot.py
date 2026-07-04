"""Discord bot runtime — state, leases, stream lifecycle, and cog wiring."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord.ext import commands

from .lease import PlaybackLease
from .models import PlaybackState
from .stream import MonitorAudioSource

logger = logging.getLogger(__name__)


class ObibokBot(commands.Bot):
    def __init__(
        self,
        engine,
        monitor,
        root_dir: str,
        sink_name: str = "robbo_bot",
        command_prefix: str = "!",
        guild_id: int | None = None,
        auto_start_channel: str = "",
        default_loop: bool = False,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.reactions = True
        # NOTE: members intent requires manual enable in Discord Developer Portal
        # intents.members = True
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.engine = engine
        self.monitor = monitor
        self.root_dir = root_dir
        self.sink_name = sink_name
        self.guild_id = guild_id
        self.auto_start_channel = auto_start_channel
        self.default_loop = default_loop
        self.playback_lease = PlaybackLease()
        self._states: dict[int, PlaybackState] = {}
        self._np_messages: dict[int, dict] = {}
        self._monitor_tasks: dict[int, asyncio.Task] = {}
        self._predownload_tasks: dict[int, asyncio.Task] = {}
        self._active_streams: dict[int, MonitorAudioSource] = {}
        self._background_tasks: list[asyncio.Task] = []
        self._playback_sessions: dict[int, int] = {}
        self._np_messages_max = 200

    def _track_np_message(self, msg_id: int, data: dict[str, Any]) -> None:
        if len(self._np_messages) >= self._np_messages_max:
            oldest = next(iter(self._np_messages))
            del self._np_messages[oldest]
        self._np_messages[msg_id] = data

    def _start_stream(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        """Start or restart the MonitorAudioSource on the given voice client."""
        old = self._active_streams.pop(guild_id, None)
        if old and hasattr(old, "cleanup"):
            old.cleanup()
        source = MonitorAudioSource(sink_name=self.sink_name)
        source.source_id = id(source)
        voice_client.play(source, after=lambda e: self._on_stream_end(guild_id, e, source.source_id))
        self._active_streams[guild_id] = source

    def _stop_stream(self, guild_id: int) -> None:
        source = self._active_streams.pop(guild_id, None)
        if source and hasattr(source, "cleanup"):
            source.cleanup()

    def _on_stream_end(self, guild_id: int, error: Exception | None, source_id: int) -> None:
        if error:
            logger.warning("Stream ended with error for guild %s: %s", guild_id, error)
        current = self._active_streams.get(guild_id)
        if current is not None and getattr(current, "source_id", None) == source_id:
            self._active_streams.pop(guild_id, None)

    def try_acquire_lease(self, guild: discord.Guild) -> bool:
        return self.playback_lease.acquire(guild.id, guild.name)

    def release_lease(self, guild_id: int | None = None) -> None:
        if guild_id is None or self.playback_lease.owner_guild_id == guild_id:
            self.playback_lease.release()

    def _cancel_predownload(self, guild_id: int) -> None:
        task = self._predownload_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _cancel_monitor(self, guild_id: int) -> None:
        task = self._monitor_tasks.pop(guild_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _schedule_predownload(self, guild_id: int, state: PlaybackState) -> None:
        self._cancel_predownload(guild_id)
        task = asyncio.create_task(self.engine.predownload_next(state))
        self._predownload_tasks[guild_id] = task

    def get_state(self, guild_id: int) -> PlaybackState:
        if guild_id not in self._states:
            self._states[guild_id] = PlaybackState(guild_id=guild_id, is_looping=self.default_loop)
        return self._states[guild_id]

    async def process_commands(self, message: discord.Message) -> None:
        if self.guild_id is not None and message.guild and message.guild.id != self.guild_id:
            return
        await super().process_commands(message)

    async def setup_hook(self) -> None:
        self.remove_command("help")
        from .cogs import CollectionCog, FavoritesCog, PlaybackCog, ToolsCog

        await self.add_cog(PlaybackCog(self))
        await self.add_cog(CollectionCog(self))
        await self.add_cog(FavoritesCog(self))
        await self.add_cog(ToolsCog(self))
        self._background_tasks.append(asyncio.create_task(self._health_watchdog()))

    async def close(self) -> None:
        for task in self._background_tasks:
            task.cancel()
        for task in self._background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Background task failed during shutdown: %s", exc)
        self._background_tasks.clear()
        for guild_id in list(self._active_streams):
            self._stop_stream(guild_id)
        for task in list(self._predownload_tasks.values()):
            task.cancel()
        self._predownload_tasks.clear()
        for task in list(self._monitor_tasks.values()):
            task.cancel()
        self._monitor_tasks.clear()
        await super().close()

    async def _health_watchdog(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(30)
            elapsed = 0.0
            try:
                t0 = asyncio.get_event_loop().time()
                await asyncio.to_thread(self.engine.audio.ensure_ready)
                elapsed = asyncio.get_event_loop().time() - t0
                if elapsed > 0.5:
                    logger.warning("Health watchdog: ensure_ready took %.2fs (long tick)", elapsed)
            except Exception as exc:
                logger.warning("Health watchdog failed after %.2fs: %s", elapsed, exc)


from .cogs import CollectionCog, FavoritesCog, PlaybackCog, ToolsCog

