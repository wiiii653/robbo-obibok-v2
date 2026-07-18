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
from .voice_streams import VoiceStreamManager

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
        self._sleep_tasks: dict[int, asyncio.Task] = {}
        self.streams = VoiceStreamManager(sink_name, self._on_stream_end_callback)
        self._background_tasks: list[asyncio.Task] = []
        self._playback_sessions: dict[int, int] = {}
        self._stream_restart_attempts: dict[int, int] = {}
        self._voice_reconnect_attempts: dict[int, int] = {}
        self._pending_voice_reconnects: set[int] = set()
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

    def track_now_playing_message(self, msg_id: int, data: dict[str, Any]) -> None:
        """Register a now-playing message for reaction-based favorites."""
        self._track_np_message(msg_id, data)

    def start_stream(
        self, guild_id: int, voice_client: discord.VoiceClient, *, reset_attempts: bool = True
    ) -> None:
        """Start or restart the Discord audio stream for a guild."""
        if self.streams.start(guild_id, voice_client) and reset_attempts:
            self._stream_restart_attempts[guild_id] = 0

    def stop_stream(self, guild_id: int) -> None:
        """Stop the Discord audio stream while keeping voice connected."""
        self.streams.stop(guild_id)

    def _on_stream_end_callback(
        self, guild_id: int, error: Exception | None, source_id: int
    ) -> None:
        """Bridge Discord's audio-thread callback onto the asyncio event loop."""
        self.loop.call_soon_threadsafe(self._schedule_stream_end, guild_id, error, source_id)

    def _schedule_stream_end(self, guild_id: int, error: Exception | None, source_id: int) -> None:
        asyncio.create_task(self._on_stream_end_on_loop(guild_id, error, source_id))

    async def _on_stream_end_on_loop(
        self, guild_id: int, error: Exception | None, source_id: int
    ) -> None:
        if error:
            self.increment_metric("stream_restarts")
            logger.warning("Stream ended with error for guild %s: %s", guild_id, error)
        is_current = self.streams.remove_if_current(guild_id, source_id)
        if error and is_current:
            asyncio.create_task(self._restart_stream_after_error(guild_id))

    async def _restart_stream_after_error(self, guild_id: int) -> None:
        attempts = self._stream_restart_attempts.get(guild_id, 0) + 1
        self._stream_restart_attempts[guild_id] = attempts
        if attempts > 5:
            logger.error("Stream restart limit reached for guild %s; ending session", guild_id)
            state = self.get_state(guild_id)
            await self.engine.stop(state)
            await self.cancel_monitor(guild_id)
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
            self.start_stream(guild_id, vc, reset_attempts=False)

    def try_acquire_lease(self, guild: discord.Guild) -> bool:
        return self.playback_lease.acquire(guild.id, guild.name)

    def release_lease(self, guild_id: int | None = None) -> None:
        if guild_id is None or self.playback_lease.owner_guild_id == guild_id:
            self.playback_lease.release()

    async def cancel_monitor(self, guild_id: int) -> None:
        task = self._monitor_tasks.pop(guild_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Monitor task failed during cancellation: %s", exc)

    def get_monitor_task(self, guild_id: int) -> asyncio.Task | None:
        return self._monitor_tasks.get(guild_id)

    def register_monitor_task(self, guild_id: int, task: asyncio.Task) -> None:
        self._monitor_tasks[guild_id] = task

    def clear_monitor_task(self, guild_id: int, task: asyncio.Task | None) -> None:
        if self._monitor_tasks.get(guild_id) is task:
            self._monitor_tasks.pop(guild_id, None)

    def cancel_sleep_task(self, guild_id: int) -> bool:
        """Cancel a pending sleep timer. Returns True if one was cancelled."""
        task = self._sleep_tasks.pop(guild_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            return True
        return False

    def register_sleep_task(self, guild_id: int, task: asyncio.Task) -> None:
        """Register a sleep timer, replacing any existing one for the guild."""
        self.cancel_sleep_task(guild_id)
        self._sleep_tasks[guild_id] = task

    def clear_sleep_task(self, guild_id: int, task: asyncio.Task | None) -> None:
        if self._sleep_tasks.get(guild_id) is task:
            self._sleep_tasks.pop(guild_id, None)

    def begin_playback_session(self, guild_id: int) -> int:
        session = self._playback_sessions.get(guild_id, 0) + 1
        self._playback_sessions[guild_id] = session
        return session

    def playback_session(self, guild_id: int) -> int:
        return self._playback_sessions.get(guild_id, 0)

    def playback_states(self) -> tuple[tuple[int, PlaybackState], ...]:
        return tuple(self._states.items())

    async def _handle_voice_disconnect(self, guild_id: int) -> None:
        """Clear a dead voice transport before attempting a bounded reconnect."""
        self.stop_stream(guild_id)
        state = self.get_state(guild_id)
        state.is_playing = False
        await self.cancel_monitor(guild_id)
        self.release_lease(guild_id)
        self._pending_voice_reconnects.add(guild_id)

    async def _retry_voice_reconnect(self, guild_id: int) -> None:
        """Try one reconnect; watchdog ticks provide the 30-second retry interval."""
        if guild_id not in self._pending_voice_reconnects:
            return

        state = self.get_state(guild_id)
        guild = self.get_guild(guild_id)
        attempts = self._voice_reconnect_attempts.get(guild_id, 0) + 1
        self._voice_reconnect_attempts[guild_id] = attempts
        if not guild or not state.voice_channel_id:
            channel = None
        else:
            channel = guild.get_channel(state.voice_channel_id)

        if channel and isinstance(channel, discord.VoiceChannel):
            logger.warning(
                "Health watchdog: reconnecting voice for guild %s (attempt %s/3)",
                guild_id,
                attempts,
            )
            try:
                vc = guild.voice_client
                if vc:
                    await vc.disconnect()
                new_vc = await channel.connect()
                if not self.try_acquire_lease(guild):
                    await new_vc.disconnect()
                    raise RuntimeError("playback lease is owned by another guild")
                state.is_playing = True
                self._pending_voice_reconnects.discard(guild_id)
                self._voice_reconnect_attempts.pop(guild_id, None)
                playback_cog = self.get_cog("PlaybackCog")
                if playback_cog:
                    await playback_cog._recover_voice(guild_id, new_vc)
                else:
                    self.start_stream(guild_id, new_vc)
                logger.info(
                    "Health watchdog: voice reconnected for guild %s, stream recovery complete",
                    guild_id,
                )
                return
            except Exception as exc:
                logger.warning(
                    "Health watchdog: voice reconnect failed for guild %s: %s", guild_id, exc
                )
        else:
            logger.warning(
                "Health watchdog: voice_channel_id %s not found or invalid for guild %s",
                state.voice_channel_id,
                guild_id,
            )

        if attempts < 3:
            return
        logger.error(
            "Health watchdog: reconnect limit reached for guild %s; stopping playback", guild_id
        )
        self._pending_voice_reconnects.discard(guild_id)
        self._voice_reconnect_attempts.pop(guild_id, None)
        state.is_playing = False
        await self.engine.stop(state)
        await self.cancel_monitor(guild_id)
        self.release_lease(guild_id)

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
            "active_streams": self.streams.count,
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
        self.streams.close()
        sleep_tasks = list(self._sleep_tasks.values())
        for task in sleep_tasks:
            task.cancel()
        self._sleep_tasks.clear()
        monitor_tasks = list(self._monitor_tasks.values())
        for task in monitor_tasks:
            task.cancel()
        self._monitor_tasks.clear()
        await asyncio.gather(*sleep_tasks, *monitor_tasks, return_exceptions=True)
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
            for gid in self.streams.guild_ids():
                guild = self.get_guild(gid)
                if not guild:
                    continue
                vc = guild.voice_client
                if not vc or not vc.is_connected():
                    logger.warning(
                        "Health watchdog: voice disconnected for active stream in guild %s", gid
                    )
                    await self._handle_voice_disconnect(gid)
                elif not vc.is_playing():
                    logger.warning(
                        "Health watchdog: voice connected but not playing for guild %s, restarting stream",
                        gid,
                    )
                    playback_cog = self.get_cog("PlaybackCog")
                    if playback_cog:
                        await playback_cog._recover_voice(gid, vc)
                    else:
                        self.start_stream(gid, vc)
            for gid in list(self._pending_voice_reconnects):
                await self._retry_voice_reconnect(gid)
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
                if self.streams.contains(gid):
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
                            self.start_stream(gid, vc)
                else:
                    await self._handle_voice_disconnect(gid)
                    await self._retry_voice_reconnect(gid)


__all__ = ["ObibokBot", "CollectionCog", "FavoritesCog", "PlaybackCog", "ToolsCog"]
