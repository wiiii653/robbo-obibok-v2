"""Tests for models module."""

from __future__ import annotations

from src.models import COLLECTIONS, FLIP_ORDER, Collection, PlaybackState, Track


class TestTrack:
    def test_track_creation(self):
        track = Track(filepath="Games/test.sap", title="Test", author="Author")
        assert track.filepath == "Games/test.sap"
        assert track.title == "Test"
        assert track.author == "Author"

    def test_track_from_cache_entry(self):
        entry = {"path": "Games/test.sap", "size": 1024}
        track = Track.from_cache_entry(entry, "asma")
        assert track.filepath == "Games/test.sap"
        assert track.collection_id == "asma"
        assert track.file_ext == "sap"
        assert track.size == 1024

    def test_track_from_cache_entry_no_name(self):
        entry = {"path": "Games/my_song.sap"}
        track = Track.from_cache_entry(entry, "asma")
        assert track.title == "my_song"


class TestCollection:
    def test_collection_creation(self):
        col = Collection(
            id="test",
            name="Test Collection",
            extensions=["mod"],
            archive_path="archiwum/test",
            cache_file="test_cache.json",
        )
        assert col.id == "test"
        assert col.volume == 100


class TestPlaybackState:
    def test_default_state(self):
        state = PlaybackState(guild_id=123)
        assert state.guild_id == 123
        assert state.collection_mode == "asma"
        assert state.tracks == []
        assert state.is_playing is False

    def test_state_with_tracks(self):
        state = PlaybackState(
            guild_id=123,
            tracks=["a.sap", "b.sap"],
            queue=["a.sap", "b.sap"],
        )
        assert len(state.tracks) == 2
        assert len(state.queue) == 2


class TestFlipOrder:
    def test_flip_order_count(self):
        assert len(FLIP_ORDER) == 7

    def test_flip_order_matches_collections(self):
        for col_id in FLIP_ORDER:
            assert col_id in COLLECTIONS
