"""Tests for playback module."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.favorites import Favorites
from src.models import PlaybackState
from src.playback import PlaybackEngine
from src.queue import Blacklist


class TestPlaybackEngine:
    def _make_engine(self, tmp_path):
        audio = MagicMock()
        audio.play.return_value = True
        audio.stop.return_value = None
        audio.is_playing.return_value = True
        audio.set_collection_volume.return_value = None
        favs = Favorites(str(tmp_path))
        bl = Blacklist(str(tmp_path))
        return PlaybackEngine(audio=audio, favorites=favs, blacklist=bl, root_dir=str(tmp_path))

    def test_engine_creation(self, tmp_path):
        engine = self._make_engine(tmp_path)
        assert engine.audio is not None
        assert engine.favorites is not None

    def test_toggle_loop(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState()
        assert engine.toggle_loop(state) is True
        assert state.is_looping is True
        assert engine.toggle_loop(state) is False
        assert state.is_looping is False

    def test_stop(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(is_playing=True)
        engine.stop(state)
        assert state.is_playing is False
        engine.audio.stop.assert_called_once()

    def test_clear(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(queue=["a.sap", "b.sap"], position=1, is_playing=True)
        engine.clear(state)
        assert state.queue == []
        assert state.position == 0
        assert state.is_playing is False

    def test_search(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(tracks=["Games/test.sap", "Composers/other.sid", "Games/test2.sap"])
        results = engine.search("test", state)
        assert len(results) == 2

    def test_search_limit(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(tracks=[f"track{i}.sap" for i in range(20)])
        results = engine.search("track", state)
        assert len(results) == 10

    def test_queue_info(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(queue=["a.sap", "b.sap", "c.sap"], position=1)
        info = engine.queue_info(state)
        assert len(info) == 3
        assert info[1]["is_current"] is True
        assert info[0]["is_current"] is False

    def test_toggle_favorite(self, tmp_path):
        engine = self._make_engine(tmp_path)
        assert engine.toggle_favorite(1, "test.sap", "asma") is True
        assert engine.favorites.has_track(1, "test.sap") is True

    def test_blacklist_current_no_track(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState()
        assert engine.blacklist_current(1, state) is False

    def test_play_track_no_track(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState()
        assert engine.play_track(state) is None


class TestTrackEndBehavior:
    def _make_engine(self, tmp_path):
        audio = MagicMock()
        audio.play.return_value = True
        audio.stop.return_value = None
        audio.is_playing.return_value = False
        favs = Favorites(str(tmp_path))
        bl = Blacklist(str(tmp_path))
        return PlaybackEngine(audio=audio, favorites=favs, blacklist=bl, root_dir=str(tmp_path))

    def test_skip_advances_position(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(queue=["a.sap", "b.sap", "c.sap"], position=0)
        engine.skip_track(state)
        assert state.position == 1

    def test_skip_returns_none_at_end(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(queue=["a.sap"], position=0)
        engine.audio.play.return_value = True
        engine.play_track(state)
        engine.audio.is_playing.return_value = False
        result = engine.skip_track(state)
        assert result is None
