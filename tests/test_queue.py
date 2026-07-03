"""Tests for queue module."""

from __future__ import annotations

from src.models import PlaybackState
from src.queue import (
    Blacklist,
    clear_queue,
    current_track,
    jump_to,
    load_queue,
    next_track,
    restore_queue,
    save_queue,
)


class TestNextTrack:
    def test_next_track_advances(self):
        state = PlaybackState(queue=["a.sap", "b.sap", "c.sap"], position=0)
        assert next_track(state) == "b.sap"
        assert state.position == 1

    def test_next_track_wraps_with_loop(self):
        state = PlaybackState(queue=["a.sap", "b.sap"], position=1, is_looping=True)
        assert next_track(state) == "b.sap"
        assert state.position == 1

    def test_next_track_returns_none_at_end(self):
        state = PlaybackState(queue=["a.sap", "b.sap"], position=1)
        assert next_track(state) is None

    def test_next_track_empty_queue(self):
        state = PlaybackState()
        assert next_track(state) is None

    def test_next_track_loop_stays_on_current(self):
        state = PlaybackState(queue=["a.sap"], position=0, is_looping=True)
        assert next_track(state) == "a.sap"


class TestCurrentTrack:
    def test_current_track(self):
        state = PlaybackState(queue=["a.sap", "b.sap"], position=1)
        assert current_track(state) == "b.sap"

    def test_current_track_empty(self):
        state = PlaybackState()
        assert current_track(state) is None

    def test_current_track_out_of_bounds(self):
        state = PlaybackState(queue=["a.sap"], position=5)
        assert current_track(state) is None


class TestJumpTo:
    def test_jump_to_valid(self):
        state = PlaybackState(queue=["a.sap", "b.sap", "c.sap"])
        assert jump_to(state, 2) == "c.sap"
        assert state.position == 2

    def test_jump_to_invalid(self):
        state = PlaybackState(queue=["a.sap"])
        assert jump_to(state, 5) is None
        assert jump_to(state, -1) is None


class TestClearQueue:
    def test_clear_queue(self):
        state = PlaybackState(queue=["a.sap", "b.sap"], position=1)
        clear_queue(state)
        assert state.queue == []
        assert state.position == 0


class TestQueuePersistence:
    def test_save_and_load_queue(self, tmp_path):
        state = PlaybackState(
            guild_id=12345,
            queue=["a.sap", "b.sap"],
            position=1,
            is_looping=True,
            collection_mode="hvsc",
        )
        root_dir = str(tmp_path)
        assert save_queue(state, root_dir) is True

        loaded = load_queue(12345, root_dir)
        assert loaded is not None
        assert loaded["queue"] == ["a.sap", "b.sap"]
        assert loaded["position"] == 1
        assert loaded["is_looping"] is True
        assert loaded["collection_mode"] == "hvsc"

    def test_load_nonexistent(self, tmp_path):
        assert load_queue(99999, str(tmp_path)) is None

    def test_restore_queue(self):
        data = {"queue": ["x.mod"], "position": 0, "is_looping": True, "collection_mode": "tiny"}
        state = PlaybackState()
        restore_queue(data, state)
        assert state.queue == ["x.mod"]
        assert state.is_looping is True
        assert state.collection_mode == "tiny"


class TestBlacklist:
    def test_add_and_check(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        assert bl.add(1, "bad.sap") is True
        assert bl.is_blacklisted("bad.sap") is True
        assert bl.is_blacklisted("good.sap") is False

    def test_add_duplicate(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        bl.add(1, "bad.sap")
        assert bl.add(1, "bad.sap") is False

    def test_remove(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        bl.add(1, "bad.sap")
        assert bl.remove(1, "bad.sap") is True
        assert bl.is_blacklisted("bad.sap") is False

    def test_remove_nonexistent(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        assert bl.remove(1, "nope.sap") is False

    def test_remove_by_index(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        bl.add(1, "a.sap")
        bl.add(1, "b.sap")
        assert bl.remove_by_index(1, 0) == "a.sap"
        assert bl.get_tracks(1) == ["b.sap"]

    def test_remove_by_index_invalid(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        assert bl.remove_by_index(1, 0) is None

    def test_get_tracks(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        bl.add(1, "a.sap")
        bl.add(1, "b.sap")
        assert bl.get_tracks(1) == ["a.sap", "b.sap"]

    def test_filter_queue(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        bl.add(1, "b.sap")
        queue = ["a.sap", "b.sap", "c.sap"]
        assert bl.filter_queue(queue, 1) == ["a.sap", "c.sap"]

    def test_persistence(self, tmp_path):
        bl = Blacklist(str(tmp_path))
        bl.add(1, "bad.sap")
        bl2 = Blacklist(str(tmp_path))
        assert bl2.is_blacklisted("bad.sap") is True
