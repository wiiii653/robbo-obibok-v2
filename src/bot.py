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
        self._active_streams: dict[int, MonitorAudioSource] = {}
        self._background_tasks: list[asyncio.Task] = []
        self._playback_sessions: dict[int, int] = {}
        self._stream_restart_attempts: dict[int, int] = {}
        self._np_messages_max = 200
        self._started_at = time.monotonic()
        self._metrics: dict[str, int] = {
            "playback_failures": 0,
            "stream_restarts": 0,
        }

    def increment_metric(self, name: str) -> None:
        if name in self._metrics:
            self._metrics[name] += 1

    def _track_np_message(self, msg_id: int, data: dict[str, Any]) -> None:
        if len(self._np_messages) >= self._np_messages_max:
            oldest = next(iter(self._np_messages))
            del self._np_messages[oldest]
        self._np_messages[msg_id] = data

    def _start_stream(
        self, guild_id: int, voice_client: discord.VoiceClient, *, reset_attempts: bool = True
    ) -> None:
        """Start or restart the MonitorAudioSource on the given voice client."""
        if not voice_client or not voice_client.is_connected():
            logger.warning("_start_stream: voice client not connected for guild %s", guild_id)
            return
        old = self._active_streams.pop(guild_id, None)
        if old and hasattr(old, "cleanup"):
            old.cleanup()
        source = MonitorAudioSource(sink_name=self.sink_name)
        source.source_id = id(source)
        voice_client.stop()
        voice_client.play(
            source, after=lambda e: self._on_stream_end(guild_id, e, source.source_id)
        )
        self._active_streams[guild_id] = source
        if reset_attempts:
            self._stream_restart_attempts[guild_id] = 0

    def _stop_stream(self, guild_id: int) -> None:
        source = self._active_streams.pop(guild_id, None)
        if source and hasattr(source, "cleanup"):
            source.cleanup()

    def _on_stream_end(self, guild_id: int, error: Exception | None, source_id: int) -> None:
        if error:
            self.increment_metric("stream_restarts")
            logger.warning("Stream ended with error for guild %s: %s", guild_id, error)
        current = self._active_streams.get(guild_id)
        is_current = current is not None and getattr(current, "source_id", None) == source_id
        if is_current:
            self._active_streams.pop(guild_id, None)
        if error and is_current:
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._restart_stream_after_error(guild_id))
            )

    async def _restart_stream_after_error(self, guild_id: int) -> None:
        attempts = self._stream_restart_attempts.get(guild_id, 0) + 1
        self._stream_restart_attempts[guild_id] = attempts
        if attempts > 5:
            logger.error("Stream restart limit reached for guild %s; ending session", guild_id)
            state = self.get_state(guild_id)
            await self.engine.stop(state)
            await self._cancel_monitor(guild_id)
            self.release_lease(guild_id)
            guild = self.get_guild(guild_id)
            if guild and guild.voice_client:
                await guild.voice_client.disconnect()
            return
        delay = min(2 ** (attempts - 1), 16)
        logger.warning(
            "Restarting stream for guild %s in %ss (attempt %s/5)",
            guild_id,
            delay,
            attempts,
        )
        await asyncio.sleep(delay)
        guild = self.get_guild(guild_id)
        vc = guild.voice_client if guild else None
        if vc and vc.is_connected() and self.get_state(guild_id).is_playing:
            self._start_stream(guild_id, vc, reset_attempts=False)

    def try_acquire_lease(self, guild: discord.Guild) -> bool:
        return self.playback_lease.acquire(guild.id, guild.name)

    def release_lease(self, guild_id: int | None = None) -> None:
        if guild_id is None or self.playback_lease.owner_guild_id == guild_id:
            self.playback_lease.release()

    async def _cancel_monitor(self, guild_id: int) -> None:
        task = self._monitor_tasks.pop(guild_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Monitor task failed during cancellation: %s", exc)

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
        monitor_tasks = list(self._monitor_tasks.values())
        for task in monitor_tasks:
            task.cancel()
        self._monitor_tasks.clear()
        await asyncio.gather(*monitor_tasks, return_exceptions=True)
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
                    playback_cog = self.get_cog("PlaybackCog")
                    if playback_cog:
                        await playback_cog._recover_voice(gid, vc)
                    else:
                        self._start_stream(gid, vc)
            # Recover orphaned playback — state says playing but no active stream
            # (happens when voice disconnects and stream ends without RECONNECT)
            now = time.monotonic()
            min_interval = getattr(self, "_orphaned_cooldown", 60.0)
            last = getattr(self, "_last_orphaned_check", 0.0)
            if now - last < min_interval:
                continue
            self._last_orphaned_check = now
            for gid, state in list(self._states.items()):
                if not state.is_playing:
                    continue
                if gid in self._active_streams:
                    continue
                guild = self.get_guild(gid)
                if not guild:
                    continue
                vc = guild.voice_client
                if vc and vc.is_connected():
                    voice_channel = vc.channel
                    if voice_channel:
                        logger.warning(
                            "Health watchdog: voice connected but stream lost for guild %s, restarting",
                            gid,
                        )
                        playback_cog = self.get_cog("PlaybackCog")
                        if playback_cog:
                            await playback_cog._recover_voice(gid, vc)
                        else:
                            self._start_stream(gid, vc)
                elif state.voice_channel_id:
                    channel = guild.get_channel(state.voice_channel_id)
                    if channel and isinstance(channel, discord.VoiceChannel):
                        logger.warning(
                            "Health watchdog: reconnecting voice for guild %s (orphaned playback)",
                            gid,
                        )
                        try:
                            if vc:
                                await vc.disconnect()
                            new_vc = await channel.connect()
                            playback_cog = self.get_cog("PlaybackCog")
                            if playback_cog:
                                await playback_cog._recover_voice(gid, new_vc)
                            logger.info(
                                "Health watchdog: voice reconnected for guild %s, "
                                "stream recovery complete",
                                gid,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Health watchdog: voice reconnect failed for guild %s: %s",
                                gid,
                                exc,
                            )
                    else:
                        logger.warning(
                            "Health watchdog: voice_channel_id %s not found or invalid for guild %s, "
                            "stopping playback",
                            state.voice_channel_id,
                            gid,
                        )
                        state.is_playing = False
                        self.release_lease(gid)
                        await self.engine.stop(state)
                        await self._cancel_monitor(gid)
                else:
                    # No voice channel remembered — nothing to reconnect to
                    pass


__all__ = ["ObibokBot", "CollectionCog", "FavoritesCog", "PlaybackCog", "ToolsCog"]
