"""Voice stream source — reads from PulseAudio monitor sink and feeds Discord."""

from __future__ import annotations

import logging
import subprocess
import time

import discord

logger = logging.getLogger(__name__)


class MonitorAudioSource(discord.AudioSource):
    """Reads PCM audio from a PulseAudio monitor sink via ffmpeg."""

    FRAME_SIZE = 3840
    MAX_RESTARTS = 5
    RESTART_COOLDOWN = 1.0

    def __init__(
        self,
        *,
        sink_name: str,
    ) -> None:
        self.buffer = b""
        self.sink_name = sink_name
        self.process = self._start_ffmpeg()
        self._restart_count = 0
        self._last_restart_ts = 0.0

    def _start_ffmpeg(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "pulse",
                "-i",
                f"{self.sink_name}.monitor",
                "-f",
                "s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def _restart_ffmpeg(self) -> None:
        self.cleanup()
        self.process = self._start_ffmpeg()

    def read(self) -> bytes:
        while len(self.buffer) < self.FRAME_SIZE:
            if self.process.poll() is not None:
                if self._restart_count >= self.MAX_RESTARTS:
                    logger.warning(
                        "MonitorAudioSource: max restarts (%d) reached, ending stream",
                        self.MAX_RESTARTS,
                    )
                    return b""
                if time.time() - self._last_restart_ts < self.RESTART_COOLDOWN:
                    time.sleep(0.05)
                    continue
                self._last_restart_ts = time.time()
                self._restart_count += 1
                time.sleep(0.1)
                self._restart_ffmpeg()
            assert self.process.stdout is not None
            chunk = self.process.stdout.read(4096)
            if not chunk:
                return b""
            self.buffer += chunk
            self._restart_count = 0
        frame = self.buffer[: self.FRAME_SIZE]
        self.buffer = self.buffer[self.FRAME_SIZE :]
        return frame

    def cleanup(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
