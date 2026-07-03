"""Tests for audio module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.audio import (
    COLLECTION_VOLUMES,
    AudioController,
    current_song,
    get_volume,
    is_playing,
    output_length,
    play_file,
    set_volume,
    song_length,
)
from src.models import COLLECTIONS


class TestCollectionVolumes:
    def test_all_collections_have_volumes(self):
        for col_id in COLLECTIONS:
            assert col_id in COLLECTION_VOLUMES

    def test_hvsc_volume_is_120(self):
        assert COLLECTION_VOLUMES["hvsc"] == 120

    def test_others_are_100(self):
        for col_id in ["asma", "modarchive", "ay", "ym", "tiny", "kgen"]:
            assert COLLECTION_VOLUMES[col_id] == 100


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
    def test_current_song(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="test_track.sap\n")
        assert current_song() == "test_track.sap"

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
        mock_audtool.side_effect = [
            True,   # playlist-clear
            True,   # playlist-addurl
            True,   # playback-play (attempt 1)
            False,  # playback-playing (attempt 1)
            True,   # playback-play (attempt 2)
            False,  # playback-playing (attempt 2)
            True,   # playback-play (attempt 3)
            False,  # playback-playing (attempt 3)
            True,   # playlist-clear (cleanup)
        ]
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

    @patch("src.audio.set_volume_for_collection")
    def test_controller_set_collection_volume(self, mock_vol):
        ctrl = AudioController(sink_name="test_sink")
        ctrl.set_collection_volume("hvsc")
        mock_vol.assert_called_once_with("hvsc", "test_sink")
