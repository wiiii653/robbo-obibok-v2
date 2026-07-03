"""Track completion monitor — D-Bus polling, timeout, empty channel detection."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from .audio import AudioController
from .models import PlaybackState

logger = logging.getLogger(__name__)

GME_EXTENSIONS = {"nsf", "sap", "spc", "vgm", "vgz"}
DEFAULT_TIMEOUT = 600
GME_TIMEOUT = 600


def is_gme_format(filepath: str) -> bool:
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    return ext in GME_EXTENSIONS


def compute_timeout(song_len: int) -> int:
    if song_len > 0:
        return song_len + 30
    return DEFAULT_TIMEOUT


@dataclass
class TrackMonitor:
    audio: AudioController
    empty_timeout: int = 60
    _last_output: int = field(default=0, init=False, repr=False)
    _last_track: str = field(default="", init=False, repr=False)
    _not_playing_since: float | None = field(default=None, init=False, repr=False)

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

        while True:
            await asyncio.sleep(2)
            try:
                await self._tick(state, on_track_end, on_empty, get_voice_members)
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
            elif now - self._not_playing_since >= 3:
                logger.info("Track ended (not playing for 3s)")
                self._not_playing_since = None
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

        if elapsed < self._last_output:
            logger.info("Track ended (output reset %d->%d)", self._last_output, elapsed)
            state.is_playing = False
            await on_track_end(state)
            return

        self._last_output = elapsed

        total = await asyncio.to_thread(self.audio.song_length)
        timeout = compute_timeout(total)
        if elapsed >= timeout:
            logger.info("Track timeout (%ds >= %ds)", elapsed, timeout)
            state.is_playing = False
            await on_track_end(state)
            return

        if get_voice_members and on_empty:
            members = await asyncio.to_thread(get_voice_members)
            if members == 0:
                logger.info("Empty channel, disconnecting")
                await on_empty()
                return
