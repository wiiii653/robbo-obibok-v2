"""Opt-in host checks for external audio dependencies."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.integration


def test_audio_binaries_are_available_on_host():
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to run host integration checks")

    missing = [name for name in ("audtool", "ffmpeg", "pactl") if shutil.which(name) is None]
    assert not missing, f"missing required audio binaries: {', '.join(missing)}"


def test_ffmpeg_can_produce_discord_pcm_frames():
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to run host integration checks")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")

    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "pipe:1",
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert len(result.stdout) >= 3840
