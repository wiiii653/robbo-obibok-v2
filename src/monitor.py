"""Track completion monitor — D-Bus polling, timeout, empty channel detection."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from .audio import AudioController
from .models import PlaybackState

logger = logging.getLogger(__name__)

GME_EXTENSIONS = {"nsf", "sap", "vgm", "vgz", "sid", "ay", "ym"}
DEFAULT_TIMEOUT = 600
GME_TIMEOUT = 600


def is_gme_format(filepath: str) -> bool:
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    return ext in GME_EXTENSIONS


def compute_timeout(song_len: int, *, is_gme_format: bool = False) -> int:
    if is_gme_format:
        return GME_TIMEOUT
    if 10 < song_len < 36000:
        return song_len + 15
    return DEFAULT_TIMEOUT


def should_confirm_output_drop(
    last_output_len: int,
    current_secs: int,
    drop_confirmed_since: float | None,
    now: float,
    grace_seconds: int,
    *,
    is_gme_format: bool,
) -> tuple[bool, float | None]:
    if is_gme_format:
        return False, None
    if last_output_len > 10 and current_secs < 5:
        if drop_confirmed_since is None:
            return False, now
        if now - drop_confirmed_since >= grace_seconds:
            return True, None
        return False, drop_confirmed_since
    return False, None


def should_advance_after_stop(
    not_playing_since: float | None,
    now: float,
    grace_seconds: int,
) -> tuple[bool, float | None]:
    if not_playing_since is None:
        return False, now
    if now - not_playing_since >= grace_seconds:
        return True, None
    return False, not_playing_since


@dataclass
class TrackMonitor:
    audio: AudioController
    empty_timeout: int = 60
    _last_output: int = field(default=0, init=False, repr=False)
    _last_track: str = field(default="", init=False, repr=False)
    _not_playing_since: float | None = field(default=None, init=False, repr=False)
    _empty_since: float | None = field(default=None, init=False, repr=False)
    _drop_confirmed_since: float | None = field(default=None, init=False, repr=False)

    async def monitor_loop(
        self,
        state: PlaybackState,
        on_track_end: callable,
        on_empty: callable | None = None,
        get_voice_members: callable | None = None,
    ) -> None:
        self._last_output = 0
        self._last_track = ""
        self._not_playing_since = None
        self._empty_since = None
        self._drop_confirmed_since = None

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
        on_track_end: callable,
        on_empty: callable | None,
        get_voice_members: callable | None,
    ) -> None:
        if not state.is_playing:
            return

        playing = await asyncio.to_thread(self.audio.is_playing)

        if not playing:
            now = asyncio.get_event_loop().time()
            if self._not_playing_since is None:
                self._not_playing_since = now
            else:
                should_advance, self._not_playing_since = should_advance_after_stop(
                    self._not_playing_since, now, 3
                )
                if should_advance:
                    logger.info("Track ended (not playing for 3s)")
                    self._drop_confirmed_since = None
                    state.is_playing = False
                    await on_track_end(state)
            return

        self._not_playing_since = None
        elapsed = await asyncio.to_thread(self.audio.output_length)
        if elapsed < 0:
            return

        track = state.current_track
        if track != self._last_track:
            self._last_track = track
            self._last_output = 0
            self._drop_confirmed_since = None

        is_gme = is_gme_format(track)
        if elapsed < self._last_output:
            now_loop = asyncio.get_running_loop().time()
            if self._last_output > 10 and elapsed < 5:
                drop_confirmed, self._drop_confirmed_since = should_confirm_output_drop(
                    self._last_output,
                    elapsed,
                    self._drop_confirmed_since,
                    now_loop,
                    3,
                    is_gme_format=is_gme,
                )
                if drop_confirmed:
                    logger.info("Track ended (confirmed output drop %d->%d)", self._last_output, elapsed)
                    self._drop_confirmed_since = None
                    state.is_playing = False
                    await on_track_end(state)
                return
            logger.info("Track ended (output reset %d->%d)", self._last_output, elapsed)
            state.is_playing = False
            await on_track_end(state)
            return
        self._drop_confirmed_since = None

        self._last_output = elapsed

        total = await asyncio.to_thread(self.audio.song_length)
        timeout = compute_timeout(total, is_gme_format=is_gme)
        if elapsed >= timeout:
            logger.info("Track timeout (%ds >= %ds)", elapsed, timeout)
            state.is_playing = False
            await on_track_end(state)
            return

        if get_voice_members and on_empty:
            members = await asyncio.to_thread(get_voice_members)
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
                return
            self._empty_since = None
