"""Tests for audio module."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from src.audio import (
    AudioController,
    FORMAT_VOLUMES,
    load_format_volumes_from_dict,
    get_volume,
    is_playing,
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
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Volume: front-left: 80 /  80%"
        )
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
        )

    @patch("src.audio.subprocess.run")
    def test_set_volume_clamps_max(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        set_volume("test_sink", 250)
        mock_run.assert_called_with(
            ["pactl", "set-sink-volume", "test_sink", "200%"],
            capture_output=True,
        )

    @patch("src.audio.subprocess.run")
    def test_set_volume_clamps_min(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        set_volume("test_sink", -10)
        mock_run.assert_called_with(
            ["pactl", "set-sink-volume", "test_sink", "0%"],
            capture_output=True,
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

    @patch("src.audio._audtool_call")
    @patch("src.audio._audacious_ready", True)
    def test_play_file_failure(self, mock_audtool):
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
    @patch("src.audio._audtool_call")
    def test_start_player_cleans_up_on_timeout(self, mock_tool, mock_popen, mock_sleep):
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_tool.return_value = False
        from src.audio import start_player
        import src.audio

        src.audio._audacious_ready = False

        assert start_player("test_sink") is False
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)

    @patch("src.audio.subprocess.run")
    @patch("src.audio._audtool_call")
    def test_kill_player(self, mock_tool, mock_run):
        mock_tool.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        from src.audio import kill_player
        kill_player()
        mock_tool.assert_any_call("playback-stop")
        mock_run.assert_called_once()

    @patch("src.audio._audtool_call")
    def test_stop_playback(self, mock_tool):
        mock_tool.return_value = True
        from src.audio import stop_playback
        stop_playback()
        assert mock_tool.call_count == 2

    @patch("src.audio.subprocess.run")
    @patch("src.audio._audtool_call")
    def test_ensure_audacious_alive(self, mock_tool, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1234")
        mock_tool.return_value = True
        from src.audio import ensure_audacious, _audacious_ready
        import src.audio
        src.audio._audacious_ready = True
        ensure_audacious()
        assert mock_tool.call_count >= 1

    @patch("src.audio.start_player")
    @patch("src.audio.subprocess.run")
    @patch("src.audio._audtool_call")
    def test_ensure_audacious_dead(self, mock_tool, mock_run, mock_start):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=0),
        ]
        mock_tool.side_effect = [True]
        mock_start.return_value = True
        from src.audio import ensure_audacious
        import src.audio
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

    @patch("src.audio.subprocess.run")
    def test_is_audacious_alive_true(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="1234\n"),
            MagicMock(returncode=0),
        ]
        from src.audio import _is_audacious_alive
        assert _is_audacious_alive() is True

    @patch("src.audio.subprocess.run")
    def test_is_audacious_alive_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        from src.audio import _is_audacious_alive
        assert _is_audacious_alive() is False


class TestAudioConfig:
    def test_set_volume_for_playback_sid(self):
        from src.audio import set_volume_for_playback
        with patch("src.audio.set_volume") as mock_set:
            set_volume_for_playback("track.sid", "test_sink")
            mock_set.assert_called_with('test_sink', 115)

    def test_set_volume_for_playback_other(self):
        from src.audio import set_volume_for_playback
        with patch("src.audio.set_volume") as mock_set:
            set_volume_for_playback("track.ay", "test_sink")
            mock_set.assert_called_with('test_sink', 100)

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
        mock_tool.assert_called_with("plugin-enable", "compressor", "TRUE")

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
