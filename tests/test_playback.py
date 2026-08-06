"""Tests for playback module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
    async def test_queue_save_failure_does_not_start_debounce(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        state = PlaybackState(guild_id=123, queue=["a.sap"], position=0)
        save_mock = MagicMock(side_effect=[False, True])
        monkeypatch.setattr("src.playback.save_queue", save_mock)

        await engine._save_queue(state)
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
    async def test_queue_save_first_save_on_fresh_clock(self, tmp_path, monkeypatch):
        """First save must not be debounced when monotonic() is small.

        GitHub CI runners are freshly provisioned VMs — time.monotonic() is
        < QUEUE_SAVE_MIN_INTERVAL at job start. The old sentinel default of
        0.0 treated "never saved" as "saved at time 0", so the first save was
        wrongly debounced (3 tests failed on CI only).
        """
        from src import playback as playback_module

        engine = self._make_engine(tmp_path)
        state = PlaybackState(guild_id=123, queue=["a.sap"], position=0)
        save_mock = MagicMock(return_value=True)
        monkeypatch.setattr("src.playback.save_queue", save_mock)
        monkeypatch.setattr("src.playback.time.monotonic", lambda: 5.0)

        await engine._save_queue(state)
        assert save_mock.call_count == 1

        # Still inside the window -> debounced
        await engine._save_queue(state)
        assert save_mock.call_count == 1

        # Past the window -> saves again
        engine._last_queue_save[123] -= playback_module.QUEUE_SAVE_MIN_INTERVAL + 1
        await engine._save_queue(state)
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

    def test_build_track_path_rejects_unsafe_paths(self, tmp_path):
        engine = self._make_engine(tmp_path)
        from src.models import COLLECTIONS

        assert engine._build_track_path(COLLECTIONS["asma"], "../escape.sap") is None
        assert engine._build_track_path(COLLECTIONS["asma"], "/abs/path.sap") is None

    def test_build_track_path_stays_under_archive(self, tmp_path):
        engine = self._make_engine(tmp_path)
        from src.models import COLLECTIONS

        path = engine._build_track_path(COLLECTIONS["asma"], "dir/good.sap")
        assert path == tmp_path / "archiwum" / "asma" / "dir" / "good.sap"

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


class TestStartRadioLock:
    def _make_engine(self, tmp_path):
        audio = MagicMock()
        audio.play.return_value = True
        audio.stop.return_value = None
        favs = Favorites(str(tmp_path))
        bl = Blacklist(str(tmp_path))
        return PlaybackEngine(audio=audio, favorites=favs, blacklist=bl, root_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_start_radio_serializes_stop(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        engine._save_queue = AsyncMock()
        state = PlaybackState()
        load_started = asyncio.Event()
        release_load = asyncio.Event()

        async def direct_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("src.playback.asyncio.to_thread", direct_to_thread)

        async def fake_start(*args, **kwargs):
            load_started.set()
            await release_load.wait()
            return "first.sap"

        monkeypatch.setattr(engine, "_start_radio_unlocked", fake_start)

        start_task = asyncio.create_task(engine.start_radio(state))
        await load_started.wait()
        stop_task = asyncio.create_task(engine.stop(state))
        await asyncio.sleep(0)
        assert not stop_task.done()

        release_load.set()
        await start_task
        await stop_task
        assert state.is_playing is False

    @pytest.mark.asyncio
    async def test_start_radio_and_play_holds_lock_through_play(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        engine._save_queue = AsyncMock()
        state = PlaybackState(guild_id=123)
        load_started = asyncio.Event()
        release_load = asyncio.Event()
        play_started = asyncio.Event()
        release_play = asyncio.Event()
        play_calls = 0

        async def blocked_play(current_state):
            nonlocal play_calls
            play_calls += 1
            assert current_state.queue == ["first.sap"]
            if play_calls == 1:
                play_started.set()
                await release_play.wait()
            return "first.sap"

        monkeypatch.setattr(engine, "_play_track_unlocked", blocked_play)

        async def fake_start(*args, **kwargs):
            load_started.set()
            await release_load.wait()
            state.queue = ["first.sap"]
            return "first.sap"

        monkeypatch.setattr(engine, "_start_radio_unlocked", fake_start)

        start_task = asyncio.create_task(engine.start_radio_and_play(state))
        await load_started.wait()
        release_load.set()
        await play_started.wait()

        competing_play = asyncio.create_task(engine.play_track(state))
        await asyncio.sleep(0)
        assert not competing_play.done()

        release_play.set()
        assert await start_task == "first.sap"
        assert await competing_play == "first.sap"

    @pytest.mark.asyncio
    async def test_start_radio_locked_wrapper_builds_and_resets_state(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        engine._save_queue = AsyncMock()

        async def direct_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("src.playback.asyncio.to_thread", direct_to_thread)
        engine.shuffle_queue = False
        state = PlaybackState(
            guild_id=123,
            current_track="stale.sap",
            current_collection_id="tiny",
            voice_channel_id=999,
            search_results=["stale.sap"],
            search_collection_id="tiny",
        )
        monkeypatch.setattr(
            "src.playback.load_raw_paths", lambda *args: ["first.sap", "second.sap"]
        )

        result = await engine.start_radio(state)

        assert result == "first.sap"
        assert state.queue == ["first.sap", "second.sap"]
        assert state.current_track == ""
        assert state.current_collection_id == ""
        assert state.voice_channel_id is None
        assert state.search_results == []
        assert state.search_collection_id == ""

    @pytest.mark.asyncio
    async def test_start_radio_uses_independent_guild_locks(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path)
        engine._save_queue = AsyncMock()
        state_a = PlaybackState(guild_id=123)
        state_b = PlaybackState(guild_id=456)
        load_a_started = asyncio.Event()
        release_a = asyncio.Event()
        first_load = True

        async def fake_start(current_state, *args, **kwargs):
            nonlocal first_load
            if first_load:
                first_load = False
                load_a_started.set()
                await release_a.wait()
            return current_state.queue[0]

        state_a.queue = ["track-a.sap"]
        state_b.queue = ["track-b.sap"]
        monkeypatch.setattr(engine, "_start_radio_unlocked", fake_start)

        task_a = asyncio.create_task(engine.start_radio(state_a))
        await load_a_started.wait()
        task_b = asyncio.create_task(engine.start_radio(state_b))
        assert await asyncio.wait_for(task_b, timeout=1) == "track-b.sap"
        assert not task_a.done()

        release_a.set()
        assert await task_a == "track-a.sap"


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
