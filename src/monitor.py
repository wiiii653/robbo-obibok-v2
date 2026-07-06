"""Track completion monitor — D-Bus polling, timeout, empty channel detection."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .audio import AudioController
from .models import PlaybackState

logger = logging.getLogger(__name__)

CONSOLE_EXTENSIONS = {"nsf", "sap", "vgm", "vgz", "sid", "ay", "ym"}
DEFAULT_TIMEOUT = 600
CONSOLE_TIMEOUT = 3600


def is_console_format(filepath: str) -> bool:
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    return ext in CONSOLE_EXTENSIONS


def compute_timeout(song_len: int, *, is_console_format: bool = False) -> int:
    if is_console_format:
        if song_len <= 0:
            return CONSOLE_TIMEOUT
        if song_len < 36000:
            return min(song_len + 0, CONSOLE_TIMEOUT)
        return CONSOLE_TIMEOUT
    if song_len <= 0:
        return CONSOLE_TIMEOUT
    if 10 < song_len < 36000:
        return song_len + 0
    return DEFAULT_TIMEOUT


def should_confirm_output_drop(
    output: int,
    last_output: int,
    confirmed_since: float | None,
    now: float,
    grace_seconds: int,
    *,
    is_console_format: bool = False,
) -> tuple[bool, float | None]:
    if is_console_format:
        return False, None
    if confirmed_since is None:
        return False, now
    if now - confirmed_since >= grace_seconds:
        return True, None
    return False, confirmed_since



def should_advance_after_stop(
    not_playing_since: float | None,
    now: float,
    grace_seconds: int,
    *,
    still_loaded: bool = False,
) -> tuple[bool, float | None]:
    if not_playing_since is None:
        return False, now
    if now - not_playing_since >= grace_seconds and not still_loaded:
        return True, None
    return False, not_playing_since


@dataclass
class TrackMonitor:
    audio: AudioController
    empty_timeout: int = 0
    _last_output: int = field(default=0, init=False, repr=False)
    _last_track: str = field(default="", init=False, repr=False)
    _cached_song_length: int = field(default=-1, init=False, repr=False)
    _not_playing_since: float | None = field(default=None, init=False, repr=False)
    _empty_since: float | None = field(default=None, init=False, repr=False)
    _drop_confirmed_since: float | None = field(default=None, init=False, repr=False)
    _track_started_at: float = field(default=0.0, init=False, repr=False)
    _was_playing: bool = field(default=False, init=False, repr=False)

    async def monitor_loop(
        self,
        state: PlaybackState,
        on_track_end: Callable[[PlaybackState], Awaitable[None]],
        on_empty: Callable[[], Awaitable[None]] | None = None,
        get_voice_members: Callable[[], int] | None = None,
    ) -> None:
        self._last_output = 0
        self._last_track = ""
        self._cached_song_length = -1
        self._not_playing_since = None
        self._empty_since = None
        self._drop_confirmed_since = None
        self._track_started_at = asyncio.get_running_loop().time()

        while True:
            await asyncio.sleep(2)
            try:
                await self._tick(state, on_track_end, on_empty, get_voice_members)
                if not state.is_playing:
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("monitor tick error: %s", exc)

    async def _tick(
        self,
        state: PlaybackState,
        on_track_end: Callable[[PlaybackState], Awaitable[None]],
        on_empty: Callable[[], Awaitable[None]] | None,
        get_voice_members: Callable[[], int] | None,
    ) -> None:
        if not state.is_playing:
            return

        if get_voice_members and on_empty:
            members = get_voice_members()
            if members == 0:
                now = asyncio.get_running_loop().time()
                if self.empty_timeout <= 0:
                    logger.info("Empty channel, disconnecting immediately")
                    self._empty_since = None
                    await on_empty()
                    return
                if self._empty_since is None:
                    self._empty_since = now
                elif now - self._empty_since >= self.empty_timeout:
                    logger.info("Empty channel for %ds, disconnecting", self.empty_timeout)
                    self._empty_since = None
                    await on_empty()
                return
            self._empty_since = None

        if hasattr(self.audio, "async_is_playing"):
            playing = await self.audio.async_is_playing()
        else:
            playing = self.audio.is_playing()

        if not playing:
            now = asyncio.get_running_loop().time()
            if not self._was_playing:
                if self._track_started_at > 0 and now - self._track_started_at > 30:
                    logger.warning("Track never started playing within 30s, ending")
                    state.is_playing = False
                    await on_track_end(state)
                elif self._track_started_at == 0:
                    pass
                else:
                    return
            if self._not_playing_since is None:
                self._not_playing_since = now
            else:
                # Check if audacious still has a track loaded (v1 compat)
                if hasattr(self.audio, "async_current_song"):
                    still_loaded = bool(await self.audio.async_current_song())
                elif hasattr(self.audio, "current_song"):
                    still_loaded = bool(self.audio.current_song())
                else:
                    still_loaded = bool(self.audio.song_length())
                grace = 8 if is_console_format(state.current_track) else 1
                should_advance, self._not_playing_since = should_advance_after_stop(
                    self._not_playing_since, now, grace, still_loaded=still_loaded
                )
                if should_advance:
                    logger.info("Track ended (not playing for %ds)", grace)
                    self._drop_confirmed_since = None
                    state.is_playing = False
                    await on_track_end(state)
            return

        self._not_playing_since = None
        self._was_playing = True

        track = state.current_track
        if track != self._last_track:
            self._last_track = track
            self._last_output = 0
            self._cached_song_length = -1
            self._drop_confirmed_since = None
            self._was_playing = False
            self._track_started_at = asyncio.get_running_loop().time()

        if hasattr(self.audio, "async_output_length"):
            elapsed = await self.audio.async_output_length()
        else:
            elapsed = self.audio.output_length()
        if elapsed < 0:
            return

        is_console = is_console_format(track)
        if elapsed < self._last_output:
            if is_console:
                logger.debug("Output length dropped %d->%d on console format (ignored)", self._last_output, elapsed)
                self._last_output = elapsed
                return
            # Output length resets are format quirks (MOD pattern loops,
            # GME internal loop), not real track ends. A single-track
            # audacious playlist never auto-advances, so a drop can only
            # mean a format anomaly.
            if self._last_output >= 10 and elapsed <= 5:
                # Classic drop signature: track ended, skip immediately
                logger.info("Track ended (output drop %d->%d)", self._last_output, elapsed)
                self._drop_confirmed_since = None
                state.is_playing = False
                await on_track_end(state)
                return
            # Minor drop that doesn't match the confirmation profile — ignore
            logger.debug("Output length dropped %d->%d (ignored)", self._last_output, elapsed)
            self._last_output = elapsed
            return
        self._drop_confirmed_since = None

        self._last_output = elapsed

        # Cache song_length once per track
        if self._cached_song_length < 0:
            if hasattr(self.audio, "async_song_length"):
                self._cached_song_length = await self.audio.async_song_length()
            else:
                self._cached_song_length = self.audio.song_length()
        total = self._cached_song_length
        timeout = compute_timeout(total, is_console_format=is_console)

        if is_console and total > 0:
            # Console/GME formats: output-length resets at subsong
            # transitions (GME internal track cycling). Use wall-clock
            # time since _track_started_at instead of output-length.
            now = asyncio.get_running_loop().time()
            track_time = now - self._track_started_at
            if track_time >= timeout:
                logger.info("Track timeout (wall %ds >= %ds)", track_time, timeout)
                state.is_playing = False
                await on_track_end(state)
                return
        elif elapsed >= timeout and elapsed < 10000:
            logger.info("Track timeout (%ds >= %ds)", elapsed, timeout)
            state.is_playing = False
            await on_track_end(state)
            return
