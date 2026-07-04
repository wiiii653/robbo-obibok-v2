"""Tests for models module."""

from __future__ import annotations

from src.models import COLLECTIONS, FLIP_ORDER, Collection, PlaybackState


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
