"""Tests for bot commands."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot import CollectionCog, FavoritesCog, ObibokBot, PlaybackCog
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

    def test_configured_default_loop_is_applied(self, tmp_path):
        engine = _make_engine(tmp_path)
        bot = ObibokBot(
            engine=engine,
            monitor=MagicMock(),
            root_dir=str(tmp_path),
            default_loop=True,
        )
        assert bot.get_state(999).is_looping is True

    def test_np_messages_capped(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot._np_messages_max = 3
        for i in range(5):
            bot._track_np_message(i, {"filepath": f"t{i}.sap"})
        assert len(bot._np_messages) == 3
        assert 0 not in bot._np_messages

    def test_health_snapshot_reports_runtime_state(self, tmp_path):
        bot = _make_bot(tmp_path)
        state = bot.get_state(12345)
        state.is_playing = True

        snapshot = bot.health_snapshot()

        assert snapshot["status"] == "ok"
        assert snapshot["tracked_states"] == 1
        assert snapshot["playing_guilds"] == 1
        assert snapshot["active_streams"] == 0
        assert snapshot["lease_owner"] is None
        assert snapshot["uptime_seconds"] >= 0
        assert snapshot["metrics"]["playback_failures"] == 0

    @pytest.mark.asyncio
    async def test_completed_predownload_task_is_removed(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.engine.predownload_next = AsyncMock(return_value=None)
        state = bot.get_state(12345)

        bot._schedule_predownload(12345, state)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert 12345 not in bot._predownload_tasks


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

    @pytest.mark.asyncio
    async def test_jump_awaits_engine_and_reinstalls_monitor(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        bot.get_state(123).queue = ["a.sap", "b.sap"]
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.guild.name = "Guild"
        ctx.send = AsyncMock()
        bot.playback_lease.acquire(123, "Guild")
        bot.engine.jump_to_track = AsyncMock(return_value="b.sap")
        cog._after_track_started = AsyncMock()
        cog._install_monitor = MagicMock()

        await cog.jump.callback(cog, ctx, 2)

        bot.engine.jump_to_track.assert_awaited_once_with(bot.get_state(123), 1)
        cog._after_track_started.assert_awaited_once()
        cog._install_monitor.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_jump_keeps_monitor_running(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        bot.get_state(123).queue = ["a.sap"]
        bot.playback_lease.acquire(123, "Guild")
        bot._cancel_monitor = MagicMock()
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.send = AsyncMock()

        await cog.jump.callback(cog, ctx, 2)

        bot._cancel_monitor.assert_not_called()
        ctx.send.assert_awaited_once_with("Invalid position.")

    @pytest.mark.asyncio
    async def test_reaction_remove_is_idempotent_after_restart(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = FavoritesCog(bot)
        bot._track_np_message(10, {"filepath": "song.sap", "collection_id": "asma"})
        payload = MagicMock(message_id=10, user_id=22, emoji="⭐")

        await cog.on_raw_reaction_remove(payload)

        assert bot.engine.favorites.has_track(22, "song.sap") is False

    @pytest.mark.asyncio
    async def test_collection_switch_clears_stale_inactive_state(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = CollectionCog(bot)
        state = bot.get_state(123)
        state.tracks = ["old.sap"]
        state.queue = ["old.sap"]
        state.queue_collection_ids = ["asma"]
        state.search_results = ["old.sap"]
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.voice_client = None
        ctx.send = AsyncMock()

        await cog._switch(ctx, "hvsc")

        assert state.collection_mode == "hvsc"
        assert state.tracks == []
        assert state.queue == []
        assert state.search_results == []

    @pytest.mark.asyncio
    async def test_number_selection_connects_before_playback(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        state = bot.get_state(123)
        state.search_results = ["song.sap"]
        state.search_collection_id = "asma"
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.guild.name = "Guild"
        ctx.author.voice.channel.connect = AsyncMock()
        ctx.voice_client = None
        ctx.send = AsyncMock()
        cog._play_and_monitor = AsyncMock()

        await cog.play.callback(cog, ctx, query="1")

        ctx.author.voice.channel.connect.assert_awaited_once()
        cog._play_and_monitor.assert_awaited_once_with(ctx, state)
        assert state.queue_collection_ids == ["asma"]

    @pytest.mark.asyncio
    async def test_non_owner_cannot_stop_shared_audio(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        bot.playback_lease.acquire(111, "Owner Guild")
        bot.engine.stop = AsyncMock()
        ctx = MagicMock()
        ctx.guild.id = 222
        ctx.send = AsyncMock()

        await cog.stop.callback(cog, ctx)

        bot.engine.stop.assert_not_awaited()
        ctx.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_track_start_releases_resources(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        state = bot.get_state(123)
        bot.playback_lease.acquire(123, "Guild")
        bot.engine.play_track = AsyncMock(return_value=None)
        bot.engine.stop = AsyncMock()
        bot._start_stream = MagicMock()
        bot._stop_stream = MagicMock()
        voice_client = MagicMock()
        voice_client.disconnect = AsyncMock()
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.voice_client = voice_client
        ctx.send = AsyncMock()

        await cog._play_and_monitor(ctx, state)

        bot.engine.stop.assert_awaited_once_with(state)
        bot._stop_stream.assert_called_once_with(123)
        voice_client.disconnect.assert_awaited_once()
        assert bot.playback_lease.owner_guild_id is None

    @pytest.mark.asyncio
    async def test_automatic_advance_reuses_current_monitor(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        state = bot.get_state(123)
        state.is_playing = True
        state.current_track = "a.sap"
        bot.engine.skip_track = AsyncMock(return_value="b.sap")
        cog._after_track_started = AsyncMock()
        cog._play_and_monitor = AsyncMock()

        async def monitor_once(monitored_state, on_track_end, on_empty, get_voice_members):
            await on_track_end(monitored_state)

        bot.monitor.monitor_loop = monitor_once
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.voice_client.channel.members = []

        cog._install_monitor(ctx, state)
        task = bot._monitor_tasks[123]
        await task

        bot.engine.skip_track.assert_awaited_once_with(state)
        cog._after_track_started.assert_awaited_once_with(ctx, state)
        cog._play_and_monitor.assert_not_awaited()


class TestPlaybackCommandBranches:
    @pytest.mark.asyncio
    async def test_play_requires_voice_channel(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.author.voice = None
        ctx.send = AsyncMock()

        await cog.play.callback(cog, ctx)

        ctx.send.assert_awaited_once_with("Join a voice channel first!")

    @pytest.mark.asyncio
    async def test_play_search_reports_no_results(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.author.voice.channel = MagicMock()
        ctx.send = AsyncMock()
        bot.engine.search = MagicMock(return_value=[])

        await cog.play.callback(cog, ctx, query="missing")

        ctx.send.assert_awaited_once_with("No tracks matching `missing`.")

    @pytest.mark.asyncio
    async def test_play_invalid_search_number(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        state = bot.get_state(123)
        state.search_results = ["song.sap"]
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.author.voice.channel = MagicMock()
        ctx.send = AsyncMock()

        await cog.play.callback(cog, ctx, query="2")

        ctx.send.assert_awaited_once_with("Invalid number. Use !search first.")

    @pytest.mark.asyncio
    async def test_skip_requires_lease_owner(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        bot.playback_lease.acquire(999, "Other")
        bot.engine.skip_track = AsyncMock()
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.send = AsyncMock()

        await cog.skip.callback(cog, ctx)

        ctx.send.assert_awaited_once()
        bot.engine.skip_track.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_np_and_history_report_idle_state(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.send = AsyncMock()

        await cog.np.callback(cog, ctx)
        await cog.history.callback(cog, ctx)

        assert ctx.send.await_args_list[0].args == ("Nothing playing.",)
        assert ctx.send.await_args_list[1].args == ("No history yet.",)

    @pytest.mark.asyncio
    async def test_volume_query_and_set(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.send = AsyncMock()
        bot.engine.audio.get_volume.return_value = 80

        await cog.volume.callback(cog, ctx)
        await cog.volume.callback(cog, ctx, 125)

        assert ctx.send.await_args_list[0].args == ("Volume: 80%",)
        assert ctx.send.await_args_list[1].args == ("Volume set to 125%",)
        bot.engine.audio.set_volume.assert_called_once_with(125)

    @pytest.mark.asyncio
    async def test_export_reports_empty_queue(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.send = AsyncMock()

        await cog.export.callback(cog, ctx)

        ctx.send.assert_awaited_once_with("Queue empty.")

    @pytest.mark.asyncio
    async def test_stop_releases_voice_and_lease(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        bot.playback_lease.acquire(123, "Guild")
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.voice_client.disconnect = AsyncMock()
        ctx.send = AsyncMock()

        await cog.stop.callback(cog, ctx)

        ctx.voice_client.disconnect.assert_awaited_once()
        ctx.send.assert_awaited_once_with("Stopped.")
        assert bot.playback_lease.owner_guild_id is None

    @pytest.mark.asyncio
    async def test_loop_toggles_state(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        state = bot.get_state(123)
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.send = AsyncMock()

        await cog.loop.callback(cog, ctx)

        assert state.is_looping is True
        ctx.send.assert_awaited_once_with("Loop: ON")

    @pytest.mark.asyncio
    async def test_clear_releases_voice_and_queue(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = PlaybackCog(bot)
        state = bot.get_state(123)
        state.queue = ["song.sap"]
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.voice_client.disconnect = AsyncMock()
        ctx.send = AsyncMock()

        await cog.clear.callback(cog, ctx)

        assert state.queue == []
        ctx.voice_client.disconnect.assert_awaited_once()
        ctx.send.assert_awaited_once_with("Queue cleared.")


class TestFavoritesCommandBranches:
    @pytest.mark.asyncio
    async def test_favorites_empty(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = FavoritesCog(bot)
        ctx = MagicMock()
        ctx.author.id = 7
        ctx.send = AsyncMock()

        await cog.favorites.callback(cog, ctx)

        assert "No favorites" in ctx.send.await_args.args[0]

    @pytest.mark.asyncio
    async def test_favplay_requires_voice(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = FavoritesCog(bot)
        ctx = MagicMock()
        ctx.guild = None
        ctx.author.voice = None
        ctx.send = AsyncMock()

        await cog.favplay.callback(cog, ctx)

        ctx.send.assert_awaited_once_with("Join a voice channel first!")

    @pytest.mark.asyncio
    async def test_favplay_invalid_number(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = FavoritesCog(bot)
        bot.engine.favorites.add(7, "track.sap", "Track", "asma")
        ctx = MagicMock()
        ctx.guild.id = 123
        ctx.author.id = 7
        ctx.author.voice.channel = MagicMock()
        ctx.send = AsyncMock()

        await cog.favplay.callback(cog, ctx, number="bad")

        ctx.send.assert_awaited_once_with("Usage: `!favplay <number>` or `!favplay` to play all.")

    @pytest.mark.asyncio
    async def test_blacklist_commands_handle_empty_and_invalid(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = FavoritesCog(bot)
        ctx = MagicMock()
        ctx.author.id = 7
        ctx.send = AsyncMock()

        await cog.blks.callback(cog, ctx)
        await cog.blkrm.callback(cog, ctx, 1)

        assert "No blacklisted" in ctx.send.await_args_list[0].args[0]
        assert ctx.send.await_args_list[1].args == ("Invalid index.",)

    @pytest.mark.asyncio
    async def test_favsave_and_favload_report_missing_data(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = FavoritesCog(bot)
        ctx = MagicMock()
        ctx.author.id = 7
        ctx.author.name = "User"
        ctx.guild.id = 123
        ctx.author.voice.channel = MagicMock()
        ctx.send = AsyncMock()

        await cog.favsave.callback(cog, ctx, name="saved")
        await cog.favload.callback(cog, ctx, name="missing")

        assert ctx.send.await_args_list[0].args == ("No favorites to save.",)
        assert "not found" in ctx.send.await_args_list[1].args[0]

    @pytest.mark.asyncio
    async def test_blacklist_remove_valid_item(self, tmp_path):
        bot = _make_bot(tmp_path)
        cog = FavoritesCog(bot)
        bot.engine.blacklist.add(7, "folder/song.sap")
        ctx = MagicMock()
        ctx.author.id = 7
        ctx.send = AsyncMock()

        await cog.blkrm.callback(cog, ctx, 1)

        ctx.send.assert_awaited_once_with("Removed `song.sap`.")

    @pytest.mark.asyncio
    async def test_playlists_reports_empty_library(self, tmp_path):
        bot = _make_bot(tmp_path)
        bot.root_dir = str(tmp_path)
        cog = FavoritesCog(bot)
        ctx = MagicMock()
        ctx.send = AsyncMock()

        await cog.playlists.callback(cog, ctx)

        ctx.send.assert_awaited_once_with("No saved playlists.")
