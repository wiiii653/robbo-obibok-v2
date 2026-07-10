"""Discord bot runtime — state, leases, stream lifecycle, and cog wiring."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .cogs import CollectionCog, FavoritesCog, PlaybackCog, ToolsCog
from .discord_compat import commands, discord
from .lease import PlaybackLease
from .models import PlaybackState
from .monitor import TrackMonitor
from .playback import PlaybackEngine
from .stream import MonitorAudioSource

logger = logging.getLogger(__name__)


class ObibokBot(commands.Bot):
    def __init__(
        self,
        engine: PlaybackEngine,
        monitor: TrackMonitor,
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
        self.engine: PlaybackEngine = engine
        self.monitor: TrackMonitor = monitor
        self.root_dir: str = root_dir
        self.sink_name: str = sink_name
        self.guild_id: int | None = guild_id
        self.auto_start_channel: str = auto_start_channel
        self.default_loop: bool = default_loop
        self.playback_lease: PlaybackLease = PlaybackLease()
        self._states: dict[int, PlaybackState] = {}
        self._np_messages: dict[int, dict] = {}
        self._monitor_tasks: dict[int, asyncio.Task] = {}
        self._predownload_tasks: dict[int, asyncio.Task] = {}
        self._active_streams: dict[int, MonitorAudioSource] = {}
        self._background_tasks: list[asyncio.Task] = []
        self._playback_sessions: dict[int, int] = {}
        self._np_messages_max = 200
        self._started_at = time.monotonic()
        self._metrics: dict[str, int] = {
            "playback_failures": 0,
            "stream_restarts": 0,
            "predownload_failures": 0,
        }

    def increment_metric(self, name: str) -> None:
        if name in self._metrics:
            self._metrics[name] += 1

    def _track_np_message(self, msg_id: int, data: dict[str, Any]) -> None:
        if len(self._np_messages) >= self._np_messages_max:
            oldest = next(iter(self._np_messages))
            del self._np_messages[oldest]
        self._np_messages[msg_id] = data

    def _start_stream(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        """Start or restart the MonitorAudioSource on the given voice client."""
        if not voice_client or not voice_client.is_connected():
            logger.warning("_start_stream: voice client not connected for guild %s", guild_id)
            return
        old = self._active_streams.pop(guild_id, None)
        if old and hasattr(old, "cleanup"):
            old.cleanup()
        source = MonitorAudioSource(sink_name=self.sink_name)
        source.source_id = id(source)
        voice_client.play(
            source, after=lambda e: self._on_stream_end(guild_id, e, source.source_id)
        )
        self._active_streams[guild_id] = source

    def _stop_stream(self, guild_id: int) -> None:
        source = self._active_streams.pop(guild_id, None)
        if source and hasattr(source, "cleanup"):
            source.cleanup()

    def _on_stream_end(self, guild_id: int, error: Exception | None, source_id: int) -> None:
        if error:
            self.increment_metric("stream_restarts")
            logger.warning("Stream ended with error for guild %s: %s", guild_id, error)
        current = self._active_streams.get(guild_id)
        if current is not None and getattr(current, "source_id", None) == source_id:
            self._active_streams.pop(guild_id, None)
        # If stream died but voice is still connected, restart the stream
        if error:
            vc = self.get_guild(guild_id).voice_client if self.get_guild(guild_id) else None
            if vc and vc.is_connected():
                logger.info(
                    "Stream died (error) but voice connected, restarting stream for guild %s",
                    guild_id,
                )
                self._start_stream(guild_id, vc)

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

        def on_done(completed: asyncio.Task) -> None:
            if self._predownload_tasks.get(guild_id) is completed:
                self._predownload_tasks.pop(guild_id, None)
            if not completed.cancelled() and completed.exception() is not None:
                logger.warning(
                    "Predownload task failed for guild %s: %s",
                    guild_id,
                    completed.exception(),
                )
                self.increment_metric("predownload_failures")

        task.add_done_callback(on_done)

    def health_snapshot(self) -> dict[str, object]:
        """Return a non-blocking snapshot suitable for diagnostics and support."""
        states = list(self._states.values())
        return {
            "status": "ok" if not self.is_closed() else "stopping",
            "uptime_seconds": round(max(0.0, time.monotonic() - self._started_at), 1),
            "metrics": dict(self._metrics),
            "guilds": len(self.guilds),
            "tracked_states": len(states),
            "playing_guilds": sum(1 for state in states if state.is_playing),
            "active_streams": len(self._active_streams),
            "monitor_tasks": sum(not task.done() for task in self._monitor_tasks.values()),
            "predownload_tasks": sum(not task.done() for task in self._predownload_tasks.values()),
            "background_tasks": sum(not task.done() for task in self._background_tasks),
            "lease_owner": self.playback_lease.owner_guild_id,
        }

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
        predownload_tasks = list(self._predownload_tasks.values())
        for task in predownload_tasks:
            task.cancel()
        self._predownload_tasks.clear()
        monitor_tasks = list(self._monitor_tasks.values())
        for task in monitor_tasks:
            task.cancel()
        self._monitor_tasks.clear()
        await asyncio.gather(*predownload_tasks, *monitor_tasks, return_exceptions=True)
        await super().close()

    async def _health_watchdog(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(30)
            elapsed = 0.0
            try:
                loop = asyncio.get_running_loop()
                t0 = loop.time()
                await asyncio.to_thread(self.engine.audio.ensure_ready)
                elapsed = loop.time() - t0
                if elapsed > 0.5:
                    logger.warning("Health watchdog: ensure_ready took %.2fs (long tick)", elapsed)
            except Exception as exc:
                logger.warning("Health watchdog failed after %.2fs: %s", elapsed, exc)
            # Check active voice streams
            for gid in list(self._active_streams.keys()):
                guild = self.get_guild(gid)
                if not guild:
                    continue
                vc = guild.voice_client
                if not vc or not vc.is_connected():
                    logger.warning(
                        "Health watchdog: voice disconnected for active stream in guild %s", gid
                    )
                elif not vc.is_playing():
                    logger.warning(
                        "Health watchdog: voice connected but not playing for guild %s, restarting stream",
                        gid,
                    )
                    self._start_stream(gid, vc)


__all__ = ["ObibokBot", "CollectionCog", "FavoritesCog", "PlaybackCog", "ToolsCog"]
