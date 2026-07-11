"""Voice stream source — reads from PulseAudio monitor sink and feeds Discord."""

from __future__ import annotations

import logging
import subprocess
import threading
import time

from .discord_compat import discord

logger = logging.getLogger(__name__)


class MonitorAudioSource(discord.AudioSource):
    """Reads PCM audio from a PulseAudio monitor sink via ffmpeg."""

    FRAME_SIZE = 3840
    MAX_RESTARTS = 5
    RESTART_COOLDOWN = 1.0
    STABLE_FRAMES = 25

    def __init__(
        self,
        *,
        sink_name: str,
    ) -> None:
        self.buffer = b""
        self.sink_name = sink_name
        self._lock = threading.RLock()
        self._closed = False
        self.process = self._start_ffmpeg()
        self._restart_count = 0
        self._last_restart_ts = 0.0
        self._frames_since_restart = self.STABLE_FRAMES

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
        with self._lock:
            if self._closed:
                return
            process = self.process
            self.process = None
            if process is not None:
                stdout = process.stdout
                if stdout is not None:
                    try:
                        stdout.close()
                    except (AttributeError, OSError):
                        pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
        self.buffer = b""
        with self._lock:
            if self._closed:
                return
            self.process = self._start_ffmpeg()
        self._frames_since_restart = 0

    def read(self) -> bytes:
        while len(self.buffer) < self.FRAME_SIZE:
            with self._lock:
                if self._closed:
                    return b""
                process = self.process
            if process is None:
                return b""
            if process.poll() is not None:
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
                continue
            with self._lock:
                if self._closed or self.process is not process:
                    return b""
                stdout = process.stdout
            if stdout is None:
                return b""
            try:
                chunk = stdout.read(4096)
            except (OSError, ValueError):
                # cleanup() may close stdout while the audio thread is blocked
                # in read().  Treat that as end-of-stream.
                return b""
            if not chunk:
                # Let the next iteration handle a process which exited between
                # poll() and read(), without signalling EOF to Discord yet.
                time.sleep(0.01)
                continue
            self.buffer += chunk
        frame = self.buffer[: self.FRAME_SIZE]
        self.buffer = self.buffer[self.FRAME_SIZE :]
        if self._frames_since_restart < self.STABLE_FRAMES:
            self._frames_since_restart += 1
            if self._frames_since_restart == self.STABLE_FRAMES:
                self._restart_count = 0
        return frame

    def cleanup(self) -> None:
        with self._lock:
            self._closed = True
            process = self.process
            self.process = None
            if process is None:
                return
            # Closing the pipe first unblocks an audio thread waiting in read().
            stdout = process.stdout
            if stdout is not None:
                try:
                    stdout.close()
                except (AttributeError, OSError):
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
