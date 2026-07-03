"""Tests for bot commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot import ObibokBot
from src.favorites import Favorites, PlaylistLibrary
from src.models import PlaybackState
from src.playback import PlaybackEngine
from src.queue import Blacklist


def _make_engine(tmp_path):
    audio = MagicMock()
    audio.play.return_value = True
    audio.stop.return_value = None
    audio.is_playing.return_value = False
    audio.set_collection_volume.return_value = None
    audio.get_volume.return_value = 100
    favs = Favorites(str(tmp_path))
    bl = Blacklist(str(tmp_path))
    return PlaybackEngine(audio=audio, favorites=favs, blacklist=bl, root_dir=str(tmp_path))


def _make_bot(tmp_path):
    engine = _make_engine(tmp_path)
    return ObibokBot(engine=engine, monitor=MagicMock(), root_dir=str(tmp_path))


class TestBotStateManagement:
    def test_get_state_creates(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = bot.get_state(12345)
        assert state.guild_id == 12345
        assert isinstance(state, PlaybackState)

    def test_get_state_reuses(self, tmp_path):
        bot = _make_bot(tmp_path)
        state1 = bot.get_state(12345)
        state2 = bot.get_state(12345)
        assert state1 is state2

    def test_get_state_different_guilds(self, tmp_path):
        bot = _make_bot(tmp_path)
        state1 = bot.get_state(111)
        state2 = bot.get_state(222)
        assert state1 is not state2

    def test_state_initialization(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = bot.get_state(999)
        assert state.collection_mode == "asma"
        assert state.queue == []
        assert state.is_playing is False

    def test_np_messages_capped(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot._np_messages_max = 3
        for i in range(5):
            bot._track_np_message(i, {"filepath": f"t{i}.sap"})
        assert len(bot._np_messages) == 3
        assert 0 not in bot._np_messages


class TestGuildRestriction:
    def test_check_guild_no_restriction(self, tmp_path):
        bot = _make_bot(tmp_path)
        ctx = AsyncMock()
        ctx.guild = MagicMock()
        ctx.guild.id = 1
        assert bot.check_guild(ctx) is True

    def test_check_guild_matching(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.guild_id = 1
        ctx = AsyncMock()
        ctx.guild = MagicMock()
        ctx.guild.id = 1
        assert bot.check_guild(ctx) is True

    def test_check_guild_non_matching(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.guild_id = 1
        ctx = AsyncMock()
        ctx.guild = MagicMock()
        ctx.guild.id = 2
        assert bot.check_guild(ctx) is False

    def test_check_guild_dm(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.guild_id = 1
        ctx = AsyncMock()
        ctx.guild = None
        assert bot.check_guild(ctx) is False


class TestFavoritesLogic:
    def test_toggle_favorite(self, tmp_path):
        bot = _make_bot(tmp_path)
        assert bot.engine.toggle_favorite(1, "test.sap", "asma") is True
        assert bot.engine.favorites.has_track(1, "test.sap") is True

    def test_toggle_favorite_remove(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.engine.toggle_favorite(1, "test.sap", "asma")
        assert bot.engine.toggle_favorite(1, "test.sap", "asma") is False
        assert bot.engine.favorites.has_track(1, "test.sap") is False

    def test_favsave(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.engine.toggle_favorite(1, "test.sap", "asma")
        lib = PlaylistLibrary(bot.root_dir)
        tracks = bot.engine.favorites.get_tracks(1)
        lib.save("Test Playlist", tracks, 1, "User")
        loaded = lib.load("Test Playlist")
        assert loaded is not None
        assert len(loaded["tracks"]) == 1

    def test_playlists_list(self, tmp_path):
        bot = _make_bot(tmp_path)
        lib = PlaylistLibrary(bot.root_dir)
        lib.save("P1", [{"filepath": "a.sap"}], 1, "User")
        lib.save("P2", [{"filepath": "b.sap"}, {"filepath": "c.sap"}], 2, "User")
        playlists = lib.list_playlists()
        assert len(playlists) == 2


class TestBlacklistLogic:
    def test_add_and_check(self, tmp_path):
        bot = _make_bot(tmp_path)
        assert bot.engine.blacklist.add(1, "bad.sap") is True
        assert bot.engine.blacklist.is_blacklisted("bad.sap") is True

    def test_remove(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.engine.blacklist.add(1, "bad.sap")
        assert bot.engine.blacklist.remove(1, "bad.sap") is True
        assert bot.engine.blacklist.is_blacklisted("bad.sap") is False

    def test_remove_by_index(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.engine.blacklist.add(1, "a.sap")
        bot.engine.blacklist.add(1, "b.sap")
        assert bot.engine.blacklist.remove_by_index(1, 0) == "a.sap"
        assert bot.engine.blacklist.get_tracks(1) == ["b.sap"]


class TestCollectionLogic:
    def test_flip(self, tmp_path):
        from src.collection_loader import flip_collection
        assert flip_collection("asma") == "modarchive"
        assert flip_collection("kgen") == "hvsc"

    def test_search(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState(tracks=["Games/test.sap", "Composers/other.sid"])
        results = bot.engine.search("test", state)
        assert len(results) == 1
        assert results[0] == "Games/test.sap"

    def test_search_limit(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState(tracks=[f"track{i}.sap" for i in range(20)])
        results = bot.engine.search("track", state)
        assert len(results) == 10


class TestPlaybackLogic:
    @pytest.mark.asyncio
    async def test_stop(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState(is_playing=True)
        await bot.engine.stop(state)
        assert state.is_playing is False

    @pytest.mark.asyncio
    async def test_clear(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState(queue=["a.sap"], is_playing=True)
        await bot.engine.clear(state)
        assert state.queue == []
        assert state.is_playing is False

    def test_toggle_loop(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState()
        assert bot.engine.toggle_loop(state) is True
        assert bot.engine.toggle_loop(state) is False

    def test_queue_info(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState(queue=["a.sap", "b.sap"], position=0)
        info = bot.engine.queue_info(state)
        assert len(info) == 2
        assert info[0]["is_current"] is True

    @pytest.mark.asyncio
    async def test_play_track_no_track(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState()
        assert await bot.engine.play_track(state) is None

    def test_blacklist_current_no_track(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = PlaybackState()
        assert bot.engine.blacklist_current(1, state) is False
