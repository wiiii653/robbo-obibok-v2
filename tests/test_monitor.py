"""Tests for monitor module."""

from __future__ import annotations

import asyncio

import pytest

from src.monitor import (
    CONSOLE_TIMEOUT,
    CONSOLE_TIMEOUT_UNKNOWN,
    DEFAULT_TIMEOUT,
    TrackMonitor,
    compute_timeout,
    is_console_format,
    maybe_learn_sid_length,
    should_advance_after_stop,
    should_confirm_output_drop,
)


class TestIsConsoleFormat:
    def test_sap_is_console(self):
        assert is_console_format("test.sap") is True

    def test_nsf_is_console(self):
        assert is_console_format("test.nsf") is True

    def test_mod_is_not_console(self):
        assert is_console_format("test.mod") is False

    def test_sid_is_console(self):
        assert is_console_format("test.sid") is True

    def test_no_extension(self):
        assert is_console_format("noext") is False


class TestComputeTimeout:
    def test_known_length(self):
        assert compute_timeout(120) == 121

    def test_unknown_length(self):
        # fix bc355ef: nieznana długość standardu -> DEFAULT_TIMEOUT (600), nie 3600
        assert compute_timeout(0) == DEFAULT_TIMEOUT

    def test_negative_length(self):
        assert compute_timeout(-1) == DEFAULT_TIMEOUT

    def test_unknown_length_console(self):
        # console, nieznana długość -> CONSOLE_TIMEOUT_UNKNOWN (180)
        assert compute_timeout(0, is_console_format=True) == CONSOLE_TIMEOUT_UNKNOWN

    def test_negative_length_console(self):
        assert compute_timeout(-1, is_console_format=True) == CONSOLE_TIMEOUT_UNKNOWN

    def test_console_length_uses_song_len_no_margin(self):
        assert compute_timeout(999, is_console_format=True) == 999

    def test_console_length_capped_at_3600(self):
        assert compute_timeout(5000, is_console_format=True) == CONSOLE_TIMEOUT

    def test_known_length_capped_at_600(self):
        assert compute_timeout(5000) == 600


class TestMaybeLearnSidLength:
    @staticmethod
    def _sid(tmp_path, name="mystery.sid"):
        sid = tmp_path / name
        sid.write_bytes(b"PSID" + b"\x00" * 64)
        return sid

    def test_skips_non_sid_extensions(self, monkeypatch, tmp_path):
        mod = tmp_path / "tune.mod"
        mod.write_bytes(b"M.K.")
        assert maybe_learn_sid_length(str(mod), 120) is False

    def test_skips_sids_already_known_to_databases(self, monkeypatch, tmp_path):
        sid = self._sid(tmp_path)
        monkeypatch.setattr("src.monitor.lookup_sid_total_time", lambda _p: 100)
        assert maybe_learn_sid_length(str(sid), 192) is False

    def test_rejects_sub_10s_measurements_as_noise(self, monkeypatch, tmp_path):
        sid = self._sid(tmp_path)
        monkeypatch.setattr("src.monitor.lookup_sid_total_time", lambda _p: None)
        assert maybe_learn_sid_length(str(sid), 5) is False

    def test_records_unknown_sid_measurement(self, monkeypatch, tmp_path):
        sid = self._sid(tmp_path)
        monkeypatch.setattr("src.monitor.lookup_sid_total_time", lambda _p: None)
        recorded = []
        monkeypatch.setattr(
            "src.monitor.record_sid_length",
            lambda path, seconds: recorded.append((path, seconds)) or True,
        )
        assert maybe_learn_sid_length(str(sid), 192.4) is True
        assert recorded == [(str(sid), 192)]


def _mock_audio(playing=True, output=30, length=0):
    return type(
        "MockAudio",
        (),
        {
            "is_playing": lambda self=None: playing,
            "output_length": lambda self=None: output,
            "song_length": lambda self=None: length,
        },
    )()


class TestNaturalEndLearning:
    @pytest.mark.asyncio
    async def test_not_playing_end_learns_sid_length(self, monkeypatch, tmp_path):
        sid = tmp_path / "mystery.sid"
        sid.write_bytes(b"PSID" + b"\x00" * 64)
        monkeypatch.setattr("src.monitor.lookup_sid_total_time", lambda _p: None)
        recorded = []
        monkeypatch.setattr(
            "src.monitor.record_sid_length",
            lambda path, seconds: recorded.append((path, seconds)) or True,
        )

        monitor = TrackMonitor(audio=_mock_audio(playing=False))
        loop = asyncio.get_running_loop()
        monitor._was_playing = True
        monitor._not_playing_since = loop.time() - 10
        monitor._track_started_at = loop.time() - 212
        state = type("State", (), {"is_playing": True, "current_track": str(sid)})()
        ended = []

        async def on_end(s):
            ended.append(1)
            s.is_playing = False

        await monitor._tick(state, on_end, None, None)
        assert len(ended) == 1
        assert len(recorded) == 1
        assert recorded[0][0] == str(sid)
        assert abs(recorded[0][1] - 212) <= 2

    @pytest.mark.asyncio
    async def test_known_timeout_does_not_learn(self, monkeypatch, tmp_path):
        sid = tmp_path / "known.sid"
        sid.write_bytes(b"PSID" + b"\x00" * 64)
        monkeypatch.setattr("src.monitor.lookup_sid_total_time", lambda _p: 100)
        recorded = []
        monkeypatch.setattr(
            "src.monitor.record_sid_length",
            lambda path, seconds: recorded.append((path, seconds)) or True,
        )

        monitor = TrackMonitor(audio=_mock_audio(playing=True))
        loop = asyncio.get_running_loop()
        monitor._last_track = str(sid)
        monitor._was_playing = True
        monitor._cached_song_length = 100
        monitor._total_time_cached = True
        monitor._track_started_at = loop.time() - 101
        state = type("State", (), {"is_playing": True, "current_track": str(sid)})()
        ended = []

        async def on_end(s):
            ended.append(1)
            s.is_playing = False

        await monitor._tick(state, on_end, None, None)
        assert len(ended) == 1
        assert recorded == []

    @pytest.mark.asyncio
    async def test_unknown_timeout_does_not_learn(self, monkeypatch, tmp_path):
        sid = tmp_path / "unknown.sid"
        sid.write_bytes(b"PSID" + b"\x00" * 64)
        monkeypatch.setattr("src.monitor.lookup_sid_total_time", lambda _p: None)
        recorded = []
        monkeypatch.setattr(
            "src.monitor.record_sid_length",
            lambda path, seconds: recorded.append((path, seconds)) or True,
        )

        monitor = TrackMonitor(audio=_mock_audio(playing=True))
        loop = asyncio.get_running_loop()
        monitor._last_track = str(sid)
        monitor._was_playing = True
        monitor._cached_song_length = 0
        monitor._total_time_cached = True
        monitor._track_started_at = loop.time() - 181
        state = type("State", (), {"is_playing": True, "current_track": str(sid)})()
        ended = []

        async def on_end(s):
            ended.append(1)
            s.is_playing = False

        await monitor._tick(state, on_end, None, None)
        assert len(ended) == 1
        assert recorded == []


class TestMonitorHelpers:
    def test_confirm_output_drop_waits_for_grace_period(self):
        now = 100.0
        drop, since = should_confirm_output_drop(20, 2, None, now, 3, is_console_format=False)
        assert drop is False
        assert since == now

        drop, since = should_confirm_output_drop(20, 2, since, now + 4, 3, is_console_format=False)
        assert drop is True
        assert since is None

    def test_confirm_output_drop_ignored_for_console_formats(self):
        drop, since = should_confirm_output_drop(20, 2, None, 100.0, 3, is_console_format=True)
        assert drop is False
        assert since is None

    def test_should_advance_after_stop_after_grace_period(self):
        now = 100.0
        advance, since = should_advance_after_stop(None, now, 3)
        assert advance is False
        assert since == now

        advance, since = should_advance_after_stop(since, now + 4, 3)
        assert advance is True
        assert since is None


class TestTrackMonitor:
    def test_monitor_creation(self):
        audio = type("MockAudio", (), {"is_playing": lambda: True})()
        monitor = TrackMonitor(audio=audio, empty_timeout=60)
        assert monitor.empty_timeout == 60

    @pytest.mark.asyncio
    async def test_monitor_tick_detects_track_end(self):

        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: False,
                "output_length": lambda self=None: 0,
                "song_length": lambda self=None: 0,
            },
        )()
        monitor = TrackMonitor(audio=audio)

        state = type(
            "State",
            (),
            {"is_playing": True, "current_track": "test.sap", "queue": ["test.sap"], "position": 0},
        )()
        ended = []

        async def on_end(s):
            ended.append(True)
            s.is_playing = False

        await monitor._tick(state, on_end, None, None)
        assert monitor._not_playing_since is not None

        monitor._not_playing_since = asyncio.get_running_loop().time() - 10
        await monitor._tick(state, on_end, None, None)
        assert len(ended) >= 1

    @pytest.mark.asyncio
    async def test_console_not_playing_grace_is_eight_seconds(self, monkeypatch):
        audio = type("MockAudio", (), {"is_playing": lambda self=None: False})()
        monitor = TrackMonitor(audio=audio)
        monitor._was_playing = True
        monitor._not_playing_since = asyncio.get_running_loop().time()
        state = type("State", (), {"is_playing": True, "current_track": "test.sid"})()
        grace_values = []

        def spy(not_playing_since, now, grace_seconds, **kwargs):
            grace_values.append(grace_seconds)
            return False, not_playing_since

        monkeypatch.setattr("src.monitor.should_advance_after_stop", spy)

        async def on_end(_state):
            pytest.fail("console grace period should not advance immediately")

        await monitor._tick(state, on_end, None, None)

        assert grace_values == [8]

    @pytest.mark.asyncio
    async def test_monitor_cancels(self):
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda: True,
                "output_length": lambda: 5,
                "song_length": lambda: 100,
            },
        )()
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


class TestMonitorTickBranches:
    @pytest.mark.asyncio
    async def test_tick_not_playing_returns_early(self):
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: False,
                "output_length": lambda self=None: 0,
                "song_length": lambda self=None: 0,
            },
        )()
        monitor = TrackMonitor(audio=audio)
        state = type("State", (), {"is_playing": False, "current_track": "test.sap"})()
        called = []

        async def on_end(s):
            called.append(True)

        await monitor._tick(state=state, on_track_end=on_end, on_empty=None, get_voice_members=None)
        assert len(called) == 0

    @pytest.mark.asyncio
    async def test_tick_timeout_detection(self):
        """Console format without known song length uses wall-clock timeout."""
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: 9999,
                "song_length": lambda self=None: 0,
            },
        )()
        monitor = TrackMonitor(audio=audio)
        # Simulate track started 200s ago so wall-clock fires at CONSOLE_TIMEOUT_UNKNOWN=180
        monitor._track_started_at = asyncio.get_running_loop().time() - 200
        monitor._last_track = "test.sap"  # prevent track-change reset
        monitor._was_playing = True  # simulate already-playing state
        state = type(
            "State",
            (),
            {"is_playing": True, "current_track": "test.sap", "queue": ["test.sap"], "position": 0},
        )()
        ended = []

        async def on_end(s):
            ended.append(True)
            s.is_playing = False

        await monitor._tick(state, on_end, None, None)
        assert len(ended) >= 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("track", "method_name"),
        [
            ("test.sap", "total_sap_time"),
            ("test.ay", "total_ay_time"),
            ("test.sid", "total_sid_time"),
        ],
    )
    async def test_total_console_time_is_cached_per_track(self, track, method_name):
        calls = {"count": 0}

        def total_time():
            calls["count"] += 1
            return 120

        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: 10,
                "song_length": lambda self=None: 60,
                method_name: staticmethod(total_time),
            },
        )()
        monitor = TrackMonitor(audio=audio)
        state = type("State", (), {"is_playing": True, "current_track": track})()

        async def on_end(_state):
            pytest.fail("track should not end")

        await monitor._tick(state, on_end, None, None)
        await monitor._tick(state, on_end, None, None)

        assert calls["count"] == 1
        assert monitor._cached_total_time == 120

    @pytest.mark.asyncio
    async def test_tick_output_reset_detection(self):
        """When output_length resets (new track started on same track), detect as track end."""
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: 5,
                "song_length": lambda self=None: 100,
            },
        )()
        monitor = TrackMonitor(audio=audio)
        monitor._last_output = 10  # simulate output decreasing = new track start
        monitor._last_track = "test.mod"  # same track so no track-change reset
        state = type(
            "State",
            (),
            {"is_playing": True, "current_track": "test.mod", "queue": ["test.mod"], "position": 0},
        )()
        ended = []

        async def on_end(s):
            ended.append(True)
            s.is_playing = False

        await monitor._tick(state, on_end, None, None)
        assert len(ended) >= 1

    @pytest.mark.asyncio
    async def test_tick_empty_channel(self):
        """When voice channel has no members, trigger on_empty."""
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: 10,
                "song_length": lambda self=None: 100,
            },
        )()
        monitor = TrackMonitor(audio=audio)
        state = type("State", (), {"is_playing": True, "current_track": "test.sap"})()
        emptied = []

        async def on_end(s):
            pass

        async def on_empty():
            emptied.append(True)

        await monitor._tick(state, on_end, on_empty, lambda: 0)
        assert len(emptied) >= 1

    @pytest.mark.asyncio
    async def test_tick_empty_channel_waits_for_timeout(self):
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: 10,
                "song_length": lambda self=None: 100,
            },
        )()
        monitor = TrackMonitor(audio=audio, empty_timeout=5)
        state = type("State", (), {"is_playing": True, "current_track": "test.sap"})()
        emptied = []

        async def on_end(s):
            pass

        async def on_empty():
            emptied.append(True)

        await monitor._tick(state, on_end, on_empty, lambda: 0)
        assert len(emptied) == 0
        assert monitor._empty_since is not None

        monitor._empty_since = asyncio.get_running_loop().time() - 6
        await monitor._tick(state, on_end, on_empty, lambda: 0)
        assert len(emptied) == 1

    @pytest.mark.asyncio
    async def test_tick_elapsed_negative(self):
        """When output_length returns -1, function should return early."""
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: -1,
                "song_length": lambda self=None: 0,
            },
        )()
        monitor = TrackMonitor(audio=audio)
        state = type("State", (), {"is_playing": True, "current_track": "test.sap"})()
        ended = []

        async def on_end(s):
            ended.append(True)

        await monitor._tick(state, on_end, None, None)
        assert len(ended) == 0

    @pytest.mark.asyncio
    async def test_empty_channel_checked_when_audio_telemetry_fails(self):
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: -1,
                "song_length": lambda self=None: 0,
            },
        )()
        monitor = TrackMonitor(audio=audio, empty_timeout=0)
        state = type("State", (), {"is_playing": True, "current_track": "test.sap"})()
        emptied = []

        async def on_end(s):
            pass

        async def on_empty():
            emptied.append(True)

        await monitor._tick(state, on_end, on_empty, lambda: 0)
        assert emptied == [True]

    @pytest.mark.asyncio
    async def test_tick_track_change_resets_output(self):
        """When current track changes, _last_output resets to avoid false track end."""
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: 30,
                "song_length": lambda self=None: 100,
            },
        )()
        monitor = TrackMonitor(audio=audio)
        monitor._last_output = 50
        monitor._last_track = "old.sap"
        state = type("State", (), {"is_playing": True, "current_track": "new.sap"})()
        ended = []

        async def on_end(s):
            ended.append(True)

        await monitor._tick(state, on_end, None, None)
        # track changed → _last_output reset to 0 → no false detection
        assert monitor._last_track == "new.sap"
        assert monitor._last_output == 30  # updated after tick
        assert len(ended) == 0

    @pytest.mark.asyncio
    async def test_monitor_loop_runs_ticks(self):
        """Monitor loop runs ticks until cancelled without error."""
        audio = type(
            "MockAudio",
            (),
            {
                "is_playing": lambda self=None: True,
                "output_length": lambda self=None: 5,
                "song_length": lambda self=None: 100,
            },
        )()
        monitor = TrackMonitor(audio=audio)
        state = type("State", (), {"is_playing": True, "current_track": "test.sap"})()

        async def on_end(s):
            pass

        task = asyncio.create_task(monitor.monitor_loop(state, on_end))
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert True  # reached here without error = loop ran
