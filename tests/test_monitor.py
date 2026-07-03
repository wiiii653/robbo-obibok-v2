"""Tests for monitor module."""

from __future__ import annotations

import asyncio

import pytest

from src.monitor import (
    GME_TIMEOUT,
    TrackMonitor,
    compute_timeout,
    is_gme_format,
)


class TestIsGmeFormat:
    def test_sap_is_gme(self):
        assert is_gme_format("test.sap") is True

    def test_nsf_is_gme(self):
        assert is_gme_format("test.nsf") is True

    def test_spc_is_gme(self):
        assert is_gme_format("test.spc") is True

    def test_mod_is_not_gme(self):
        assert is_gme_format("test.mod") is False

    def test_sid_is_not_gme(self):
        assert is_gme_format("test.sid") is False

    def test_no_extension(self):
        assert is_gme_format("noext") is False


class TestComputeTimeout:
    def test_known_length(self):
        assert compute_timeout(120) == 150

    def test_unknown_length(self):
        assert compute_timeout(0) == GME_TIMEOUT

    def test_negative_length(self):
        assert compute_timeout(-1) == GME_TIMEOUT


class TestTrackMonitor:
    def test_monitor_creation(self):
        audio = type("MockAudio", (), {"is_playing": lambda: True})()
        monitor = TrackMonitor(audio=audio, empty_timeout=60)
        assert monitor.empty_timeout == 60

    @pytest.mark.asyncio
    async def test_monitor_tick_detects_track_end(self):
        import time

        audio = type("MockAudio", (), {
            "is_playing": lambda self=None: False,
            "output_length": lambda self=None: 0,
            "song_length": lambda self=None: 0,
        })()
        monitor = TrackMonitor(audio=audio)

        state = type("State", (), {"is_playing": True, "current_track": "test.sap", "queue": ["test.sap"], "position": 0})()
        ended = []

        async def on_end(s):
            ended.append(True)
            s.is_playing = False

        await monitor._tick(state, on_end, None, None)
        assert monitor._not_playing_since is not None

        monitor._not_playing_since = time.monotonic() - 5
        await monitor._tick(state, on_end, None, None)
        assert len(ended) >= 1

    @pytest.mark.asyncio
    async def test_monitor_cancels(self):
        audio = type("MockAudio", (), {
            "is_playing": lambda: True,
            "output_length": lambda: 5,
            "song_length": lambda: 100,
        })()
        monitor = TrackMonitor(audio=audio)

        state = type("State", (), {"is_playing": True, "current_track": "test.sap"})()
        ended = []

        async def on_end(s):
            ended.append(True)

        task = asyncio.create_task(monitor.monitor_loop(state, on_end))
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(ended) == 0
