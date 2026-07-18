"""Tests for playback module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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

    @pytest.mark.asyncio
    async def test_stop(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(
            is_playing=True,
            current_track="song.sap",
            current_collection_id="asma",
            voice_channel_id=123,
            search_results=["old.sap"],
            search_collection_id="asma",
        )
        await engine.stop(state)
        assert state.is_playing is False
        assert state.current_track == ""
        assert state.current_collection_id == ""
        assert state.voice_channel_id is None
        assert state.search_results == []
        assert state.search_collection_id == ""
        engine.audio.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(
            queue=["a.sap", "b.sap"],
            position=1,
            is_playing=True,
            current_track="song.sap",
            current_collection_id="asma",
            voice_channel_id=123,
            search_results=["old.sap"],
            search_collection_id="asma",
        )
        await engine.clear(state)
        assert state.queue == []
        assert state.position == 0
        assert state.is_playing is False
        assert state.current_track == ""
        assert state.current_collection_id == ""
        assert state.voice_channel_id is None
        assert state.search_results == []
        assert state.search_collection_id == ""

    def test_search(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(tracks=["Games/test.sap", "Composers/other.sid", "Games/test2.sap"])
        results = engine.search("test", state)
        assert len(results) == 2

    def test_search_matches_directory(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(tracks=["Games/test.sap", "Composers/other.sid"])
        results = engine.search("games", state)
        assert results == ["Games/test.sap"]

    def test_search_matches_metadata(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(collection_mode="asma", tracks=["Composers/other.sid"])

        def fake_metadata(path, collection_id):
            return {"AUTHOR": "Chip Master"} if path.endswith("other.sid") else {}

        monkeypatch.setattr("src.playback.extract_metadata", fake_metadata)
        results = engine.search("chip", state)
        assert results == ["Composers/other.sid"]

    def test_describe_search_result(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)

        monkeypatch.setattr(
            engine,
            "get_track_metadata",
            lambda filepath, collection_id: {"NAME": "Test Track", "AUTHOR": "Coder"},
        )
        label = engine.describe_search_result("Games/test.sap", "asma", 1)
        assert "Test Track" in label
        assert "Coder" in label

    def test_search_limit(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(tracks=[f"track{i}.sap" for i in range(20)])
        results = engine.search("track", state)
        assert len(results) == 10

    def test_search_metadata_probes_capped(self, tmp_path, monkeypatch):
        """Metadata fallback must not open unbounded files on huge collections."""
        from src import playback as playback_module

        engine = self._make_engine(tmp_path)
        # No path contains the query — every track would be a metadata probe.
        state = PlaybackState(
            collection_mode="asma",
            tracks=[f"dir/{i}.sap" for i in range(2000)],
        )
        probe_count = 0

        def fake_metadata(path, collection_id):
            nonlocal probe_count
            probe_count += 1
            return {}

        monkeypatch.setattr("src.playback.extract_metadata", fake_metadata)
        results = engine.search("no-such-track", state)

        assert results == []
        assert probe_count == playback_module.MAX_METADATA_PROBES

    def test_search_path_matching_continues_after_probe_cap(self, tmp_path, monkeypatch):
        """Path matching is cheap and must keep working past the probe cap."""
        from src import playback as playback_module

        engine = self._make_engine(tmp_path)
        tracks = [f"dir/{i}.sap" for i in range(playback_module.MAX_METADATA_PROBES + 10)]
        tracks.append("dir/needle.sap")
        state = PlaybackState(collection_mode="asma", tracks=tracks)

        monkeypatch.setattr("src.playback.extract_metadata", lambda path, cid: {})
        results = engine.search("needle", state)

        assert results == ["dir/needle.sap"]

    def test_queue_info(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(queue=["a.sap", "b.sap", "c.sap"], position=1)
        info = engine.queue_info(state)
        assert len(info) == 3
        assert info[1]["is_current"] is True
        assert info[0]["is_current"] is False

    @pytest.mark.asyncio
    async def test_queue_save_debounced(self, tmp_path, monkeypatch):
        """Per-track saves within the debounce window collapse into one write."""
        from src import playback as playback_module

        engine = self._make_engine(tmp_path)
        state = PlaybackState(guild_id=123, queue=["a.sap", "b.sap"], position=0)
        save_mock = MagicMock(return_value=True)
        monkeypatch.setattr("src.playback.save_queue", save_mock)

        await engine._save_queue(state)
        await engine._save_queue(state)
        assert save_mock.call_count == 1

        # Past the debounce window -> saves again
        engine._last_queue_save[123] -= playback_module.QUEUE_SAVE_MIN_INTERVAL + 1
        await engine._save_queue(state)
        assert save_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_queue_save_immediate_bypasses_debounce(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(guild_id=123, queue=["a.sap"], position=0)
        save_mock = MagicMock(return_value=True)
        monkeypatch.setattr("src.playback.save_queue", save_mock)

        await engine._save_queue(state)
        await engine._save_queue(state, immediate=True)
        assert save_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_saves_immediately_after_recent_save(self, tmp_path, monkeypatch):
        """stop() must persist even right after a debounced per-track save."""
        engine = self._make_engine(tmp_path)
        state = PlaybackState(guild_id=123, queue=["a.sap"], position=0, is_playing=True)
        save_mock = MagicMock(return_value=True)
        monkeypatch.setattr("src.playback.save_queue", save_mock)

        await engine._save_queue(state)  # per-track save, starts the window
        await engine.stop(state)  # must not be debounced
        assert save_mock.call_count == 2

    def test_toggle_favorite(self, tmp_path):
        engine = self._make_engine(tmp_path)
        assert engine.toggle_favorite(1, "test.sap", "asma") is True
        assert engine.favorites.has_track(1, "test.sap") is True

    def test_blacklist_current_no_track(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState()
        assert engine.blacklist_current(1, state) is False

    @pytest.mark.asyncio
    async def test_play_track_no_track(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState()
        assert await engine.play_track(state) is None

    def test_mixed_queue_resolves_current_collection(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(
            collection_mode="asma",
            queue=["song.sid"],
            queue_collection_ids=["hvsc"],
        )
        path = asyncio.run(engine._resolve_track_path(state, "song.sid"))
        assert path == tmp_path / "archiwum" / "hvsc" / "C64Music" / "song.sid"

    def test_start_radio_preserves_index_order_when_shuffle_disabled(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        engine.shuffle_queue = False
        (tmp_path / "asma_cache_local.json").write_text(
            '{"tracks": [{"path": "first.sap"}, {"path": "second.sap"}]}'
        )

        def unexpected_shuffle(queue):
            raise AssertionError("shuffle must remain disabled")

        monkeypatch.setattr("random.shuffle", unexpected_shuffle)
        state = PlaybackState(
            current_track="stale.sap",
            current_collection_id="tiny",
            voice_channel_id=999,
            search_results=["stale.sap"],
            search_collection_id="tiny",
        )

        result = asyncio.run(engine.start_radio(state))
        assert result == "first.sap"
        assert state.queue == ["first.sap", "second.sap"]
        assert state.current_track == ""
        assert state.current_collection_id == ""
        assert state.voice_channel_id is None
        assert state.search_results == []
        assert state.search_collection_id == ""

    @pytest.mark.asyncio
    async def test_play_track_failure_resets_state(self, tmp_path):
        engine = self._make_engine(tmp_path)
        engine.audio.play.return_value = False
        state = PlaybackState(queue=["a.sap"], position=0, is_playing=True, current_track="old.sap")

        result = await engine.play_track(state)

        assert result is None
        assert state.is_playing is False
        assert state.current_track == ""
        assert state.current_collection_id == ""


class TestTrackEndBehavior:
    def _make_engine(self, tmp_path):
        audio = MagicMock()
        audio.play.return_value = True
        audio.stop.return_value = None
        audio.is_playing.return_value = False
        favs = Favorites(str(tmp_path))
        bl = Blacklist(str(tmp_path))
        return PlaybackEngine(audio=audio, favorites=favs, blacklist=bl, root_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_skip_advances_position(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(queue=["a.sap", "b.sap", "c.sap"], position=0)
        # Create test files so _resolve_track_path's exists() check passes
        archive_dir = Path(str(tmp_path)) / "archiwum" / "asma"
        archive_dir.mkdir(parents=True)
        for fname in ("a.sap", "b.sap", "c.sap"):
            (archive_dir / fname).write_text("SAP\n")
        await engine.skip_track(state)
        assert state.position == 1

    @pytest.mark.asyncio
    async def test_skip_returns_none_at_end(self, tmp_path):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(queue=["a.sap"], position=0)
        engine.audio.play.return_value = True
        await engine.play_track(state)
        engine.audio.is_playing.return_value = False
        result = await engine.skip_track(state)
        assert result is None
