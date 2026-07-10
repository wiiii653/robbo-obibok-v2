"""Tests for audio module."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.audio import (
    FORMAT_VOLUMES,
    SUPPORTED_AUDACIOUS_VERSION,
    AudioController,
    _get_ay_max_track,
    _get_sap_songs_count,
    _get_sap_time_seconds,
    _get_sid_songs_count,
    _parse_sap_time,
    check_audacious_version,
    disable_repeat,
    get_audacious_version,
    get_volume,
    is_playing,
    load_format_volumes_from_dict,
    output_length,
    play_file,
    set_volume,
    song_length,
)


class TestFormatVolumes:
    def test_sid_volume_is_115(self):
        assert FORMAT_VOLUMES["sid"] == 115

    def test_mod_volume_is_115(self):
        assert FORMAT_VOLUMES["mod"] == 115

    def test_others_default_to_100(self):
        assert FORMAT_VOLUMES.get("sap", 100) == 100
        assert FORMAT_VOLUMES.get("ay", 100) == 100
        assert FORMAT_VOLUMES.get("ym", 100) == 100

    def test_load_format_volumes_from_dict_merges(self):
        old = dict(FORMAT_VOLUMES)
        load_format_volumes_from_dict({"sid": 200, "sap": 150})
        assert FORMAT_VOLUMES["sid"] == 200
        assert FORMAT_VOLUMES["sap"] == 150
        assert FORMAT_VOLUMES["mod"] == old["mod"]  # unchanged
        # Cleanup
        FORMAT_VOLUMES.clear()
        FORMAT_VOLUMES.update(old)


class TestVolumeControl:
    @patch("src.audio.subprocess.run")
    def test_get_volume(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Volume: front-left: 80 /  80%")
        vol = get_volume("test_sink")
        assert vol == 80

    @patch("src.audio.subprocess.run")
    def test_get_volume_no_match(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="no volume info")
        vol = get_volume("test_sink")
        assert vol is None

    @patch("src.audio.subprocess.run")
    def test_set_volume(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        set_volume("test_sink", 150)
        mock_run.assert_called_with(
            ["pactl", "set-sink-volume", "test_sink", "150%"],
            capture_output=True,
            timeout=10,
        )

    @patch("src.audio.subprocess.run")
    def test_set_volume_clamps_max(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        set_volume("test_sink", 250)
        mock_run.assert_called_with(
            ["pactl", "set-sink-volume", "test_sink", "200%"],
            capture_output=True,
            timeout=10,
        )

    @patch("src.audio.subprocess.run")
    def test_set_volume_clamps_min(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        set_volume("test_sink", -10)
        mock_run.assert_called_with(
            ["pactl", "set-sink-volume", "test_sink", "0%"],
            capture_output=True,
            timeout=10,
        )


class TestPlaybackControl:
    @patch("src.audio.subprocess.run")
    def test_is_playing_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert is_playing() is True

    @patch("src.audio.subprocess.run")
    def test_is_playing_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert is_playing() is False

    @patch("src.audio.subprocess.run")
    def test_output_length(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="120\n")
        assert output_length() == 120

    @patch("src.audio.subprocess.run")
    def test_output_length_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert output_length() == -1

    @patch("src.audio.subprocess.run")
    def test_song_length(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="300\n")
        assert song_length() == 300

    @patch("src.audio.subprocess.run")
    def test_song_length_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="error")
        assert song_length() == -1


class TestPlayFile:
    @patch("src.audio._move_to_sink")
    @patch("src.audio._audtool_call")
    @patch("src.audio._audacious_ready", True)
    def test_play_file_success(self, mock_audtool, mock_move):
        mock_audtool.side_effect = [True, True, True, True, True]
        result = play_file("test.sap", "test_sink")
        assert result is True

    @patch("src.audio._is_audacious_alive", return_value=True)
    @patch("src.audio._audtool_call")
    @patch("src.audio._audacious_ready", True)
    def test_play_file_failure(self, mock_audtool, mock_alive):
        mock_audtool.side_effect = [True, True, True] + [False] * 10 + [True]
        result = play_file("test.sap", "test_sink")
        assert result is False


class TestAudioController:
    def test_controller_creation(self):
        ctrl = AudioController(sink_name="test_sink")
        assert ctrl.sink_name == "test_sink"

    @patch("src.audio.play_file")
    def test_controller_play(self, mock_play):
        mock_play.return_value = True
        ctrl = AudioController(sink_name="test_sink")
        assert ctrl.play("test.sap") is True
        mock_play.assert_called_once_with("test.sap", "test_sink")

    @patch("src.audio.stop_playback")
    def test_controller_stop(self, mock_stop):
        ctrl = AudioController(sink_name="test_sink")
        ctrl.stop()
        mock_stop.assert_called_once()

    @patch("src.audio.is_playing")
    def test_controller_is_playing(self, mock_playing):
        mock_playing.return_value = True
        ctrl = AudioController(sink_name="test_sink")
        assert ctrl.is_playing() is True

    @patch("src.audio.get_volume")
    def test_controller_get_volume(self, mock_vol):
        mock_vol.return_value = 80
        ctrl = AudioController(sink_name="test_sink")
        assert ctrl.get_volume() == 80

    @patch("src.audio.set_volume")
    def test_controller_set_volume(self, mock_vol):
        ctrl = AudioController(sink_name="test_sink")
        ctrl.set_volume(150)
        mock_vol.assert_called_once_with("test_sink", 150)

    @patch("src.audio.set_volume_for_playback")
    def test_controller_set_volume_for_playback(self, mock_vol):
        ctrl = AudioController(sink_name="test_sink")
        ctrl.set_volume_for_playback("/path/to/track.sid")
        mock_vol.assert_called_once_with("/path/to/track.sid", "test_sink")


class TestSinkManagement:
    @patch("src.audio.subprocess.run")
    def test_setup_sink_exists(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="robbo_test_sink")
        from src.audio import setup_sink

        assert setup_sink("robbo_test_sink") is True
        mock_run.assert_called_once()

    @patch("src.audio.subprocess.run")
    def test_setup_sink_creates(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="some_other_sink"),
            MagicMock(returncode=0),
        ]
        from src.audio import setup_sink

        assert setup_sink("robbo_test_sink") is True
        assert mock_run.call_count == 2

    @patch("src.audio.subprocess.run")
    def test_setup_sink_reports_creation_failure(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="some_other_sink"),
            MagicMock(returncode=1),
        ]
        from src.audio import setup_sink

        assert setup_sink("robbo_test_sink") is False

    @patch("src.audio.subprocess.run")
    def test_move_to_sink_only_moves_audacious(self, mock_run):
        listing = """
Sink Input #41
    Properties:
        application.name = "Firefox"
Sink Input #42
    Properties:
        application.process.binary = "audacious"
"""
        mock_run.side_effect = [MagicMock(stdout=listing), MagicMock(returncode=0)]
        from src.audio import _move_to_sink

        _move_to_sink("robbo_bot")

        assert mock_run.call_count == 2
        mock_run.assert_any_call(
            ["pactl", "move-sink-input", "42", "robbo_bot"],
            capture_output=True,
        )


class TestPlayerLifecycle:
    @patch("src.audio.time.sleep", return_value=None)
    @patch("src.audio.subprocess.Popen")
    @patch("src.audio.kill_player")
    @patch("src.audio.get_audacious_version")
    def test_start_player_cleans_up_on_timeout(
        self, mock_version, mock_kill, mock_popen, mock_sleep
    ):
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_version.return_value = None
        import src.audio
        from src.audio import start_player

        src.audio._audacious_ready = False

        assert start_player("test_sink") is False
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)

    @patch("src.audio._audtool_call")
    def test_kill_player(self, mock_tool, monkeypatch):
        mock_tool.return_value = True
        from src import audio

        process = MagicMock()
        process.poll.return_value = None
        monkeypatch.setattr(audio, "_audacious_process", process)

        audio.kill_player()
        mock_tool.assert_any_call("playback-stop")
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    @patch("src.audio._audtool_call")
    def test_stop_playback(self, mock_tool):
        mock_tool.return_value = True
        from src.audio import stop_playback

        stop_playback()
        assert mock_tool.call_count == 2

    @patch("src.audio._is_audacious_alive")
    @patch("src.audio.start_player")
    def test_ensure_audacious_alive(self, mock_start, mock_alive):
        mock_alive.return_value = True
        import src.audio
        from src.audio import ensure_audacious

        src.audio._audacious_ready = True
        ensure_audacious()
        mock_start.assert_not_called()

    @patch("src.audio.start_player")
    @patch("src.audio._is_audacious_alive")
    def test_ensure_audacious_dead(self, mock_alive, mock_start):
        mock_alive.return_value = False
        mock_start.return_value = True
        import src.audio
        from src.audio import ensure_audacious

        src.audio._audacious_ready = True
        ensure_audacious()

    @patch("src.audio.subprocess.run")
    def test_audtool_call_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        from src.audio import _audtool_call

        assert _audtool_call("version") is True
        mock_run.assert_called_with(["audtool", "version"], capture_output=True, timeout=10)

    @patch("src.audio.subprocess.run")
    def test_audtool_call_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        from src.audio import _audtool_call

        assert _audtool_call("version") is False

    @patch("src.audio.subprocess.run")
    def test_audtool_call_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("audtool", 10)
        from src.audio import _audtool_call

        assert _audtool_call("version") is False

    @patch("src.audio.get_audacious_version")
    @patch("src.audio.subprocess.run")
    def test_is_audacious_alive_true(self, mock_run, mock_version):
        mock_run.return_value = MagicMock(returncode=0)
        mock_version.return_value = "4.6.1"
        from src.audio import _is_audacious_alive

        assert _is_audacious_alive() is True

    @patch("src.audio.get_audacious_version")
    @patch("src.audio.subprocess.run")
    def test_is_audacious_alive_false(self, mock_run, mock_version):
        mock_version.return_value = None
        from src.audio import _is_audacious_alive

        assert _is_audacious_alive() is False

    @patch("src.audio.subprocess.run")
    def test_get_audacious_version_parses(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Audacious 4.6.1")
        assert get_audacious_version() == "4.6.1"

    @patch("src.audio.subprocess.run")
    def test_check_audacious_version_accepts_supported(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Audacious 4.6.1")
        assert check_audacious_version() == SUPPORTED_AUDACIOUS_VERSION

    @patch("src.audio.subprocess.run")
    def test_check_audacious_version_rejects_unsupported(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Audacious 4.6.2")
        with pytest.raises(RuntimeError):
            check_audacious_version()


class TestAudioConfig:
    def test_set_volume_for_playback_sid(self):
        from src.audio import set_volume_for_playback

        with patch("src.audio.set_volume") as mock_set:
            set_volume_for_playback("track.sid", "test_sink")
            mock_set.assert_called_with("test_sink", 115)

    def test_set_volume_for_playback_other(self):
        from src.audio import set_volume_for_playback

        with patch("src.audio.set_volume") as mock_set:
            set_volume_for_playback("track.ay", "test_sink")
            mock_set.assert_called_with("test_sink", 100)

    def test_load_format_volumes_from_dict(self):
        from src.audio import FORMAT_VOLUMES, load_format_volumes_from_dict

        old = dict(FORMAT_VOLUMES)
        load_format_volumes_from_dict({"sid": 50, "sap": 75})
        assert FORMAT_VOLUMES["sid"] == 50
        assert FORMAT_VOLUMES["sap"] == 75
        assert FORMAT_VOLUMES["mod"] == old["mod"]
        FORMAT_VOLUMES.clear()
        FORMAT_VOLUMES.update(old)

    @patch("src.audio._audtool_call")
    def test_enable_compressor(self, mock_tool):
        mock_tool.return_value = True
        from src.audio import enable_compressor

        enable_compressor()
        mock_tool.assert_called_with("plugin-enable", "compressor", "on")

    @patch("src.audio._audtool_call")
    def test_setup_sid_config(self, mock_tool):
        mock_tool.return_value = True
        from src.audio import setup_sid_config

        setup_sid_config()
        assert mock_tool.call_count == 3

    @patch("src.audio.setup_sink")
    @patch("src.audio.start_player")
    @patch("src.audio.setup_sid_config")
    @patch("src.audio.enable_compressor")
    def test_controller_setup(self, mock_comp, mock_sid, mock_start, mock_sink):
        mock_start.return_value = True
        ctrl = AudioController(sink_name="test_sink")
        ctrl.setup()
        mock_sink.assert_called_once_with("test_sink")
        mock_sid.assert_called_once()
        mock_comp.assert_called_once()

    @patch("src.audio.kill_player")
    def test_controller_kill(self, mock_kill):
        ctrl = AudioController()
        ctrl.kill()
        mock_kill.assert_called_once()

    @patch("src.audio.song_length")
    def test_controller_song_length(self, mock_len):
        mock_len.return_value = 300
        ctrl = AudioController()
        assert ctrl.song_length() == 300

    @patch("src.audio.output_length")
    def test_controller_output_length(self, mock_len):
        mock_len.return_value = 120
        ctrl = AudioController()
        assert ctrl.output_length() == 120

    @patch("src.audio.ensure_audacious")
    @patch("src.audio.setup_sink")
    def test_controller_ensure_ready(self, mock_sink, mock_ensure):
        ctrl = AudioController()
        ctrl.ensure_ready()
        mock_sink.assert_called_once_with("robbo_bot")
        mock_ensure.assert_called_once()


class TestSapTimeParsing:
    def test_parse_sap_time_standard(self):
        assert _parse_sap_time("03:20") == 200
        assert _parse_sap_time("00:44") == 44
        assert _parse_sap_time("01:00") == 60

    def test_parse_sap_time_with_milliseconds(self):
        assert _parse_sap_time("03:20.09") == 200
        assert _parse_sap_time("02:57.133") == 177
        assert _parse_sap_time("00:44.925") == 44

    def test_parse_sap_time_zero_refused(self):
        assert _parse_sap_time("00:00") is None
        assert _parse_sap_time("00:00.00") is None

    def test_parse_sap_time_invalid(self):
        assert _parse_sap_time("") is None
        assert _parse_sap_time("abc") is None
        assert _parse_sap_time("not_a_time") is None

    def test_get_sap_time_seconds(self, tmp_path):
        cases = [
            ("Sweet_Dreams.sap", "TIME 03:20\n", 200),
            ("Crocketts_Theme.sap", "TIME 03:20\n", 200),
            ("Milk_Race.sap", "SONGS 3\nTIME 01:20\nTIME 01:20\nTIME 01:30\n", 250),
            ("Pooyan.sap", "SONGS 2\nTIME 00:17\nTIME 00:17\n", 34),
        ]
        for filename, content, expected in cases:
            filepath = tmp_path / filename
            filepath.write_text(content)
            assert _get_sap_time_seconds(str(filepath)) == expected

    def test_get_sap_songs_count(self, tmp_path):
        filepath = tmp_path / "multi.sap"
        filepath.write_text("SONGS 3\n")
        assert _get_sap_songs_count(str(filepath)) == 3
        filepath.write_text("SONGS 2\n")
        assert _get_sap_songs_count(str(filepath)) == 2
        # Single-song SAP has no SONGS header
        filepath.write_text("TIME 03:20\n")
        assert _get_sap_songs_count(str(filepath)) is None


class TestAyHeader:
    def test_ay_max_track_zero_for_non_ay(self):
        assert _get_ay_max_track("/nonexistent/file.sap") == 0

    def test_ay_max_track_nonexistent(self):
        assert _get_ay_max_track("/nonexistent/file.ay") == 0


class TestSidHeader:
    def test_sid_songs_count_returns_one_for_non_sid(self):
        assert _get_sid_songs_count("/nonexistent/file.sap") == 1

    def test_sid_songs_count_nonexistent(self):
        assert _get_sid_songs_count("/nonexistent/file.sid") == 1


class TestDisableRepeat:
    @patch("src.audio.subprocess.run")
    def test_disable_repeat_turns_off_when_on(self, mock_run):
        """Simulate repeat-status=on, toggle succeeds."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="on\n"),  # status check
            MagicMock(returncode=0, stdout=""),  # toggle
        ]
        disable_repeat()
        assert mock_run.call_count >= 2

    @patch("src.audio.subprocess.run")
    def test_disable_repeat_skips_when_off(self, mock_run):
        """Simulate repeat-status=off, no toggle needed."""
        mock_run.return_value = MagicMock(returncode=0, stdout="off\n")
        disable_repeat()
        assert mock_run.call_count == 1  # only status check, no toggle
