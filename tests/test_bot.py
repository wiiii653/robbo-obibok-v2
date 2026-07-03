"""Tests for bot module."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.bot import ObibokBot
from src.favorites import Favorites
from src.models import PlaybackState
from src.playback import PlaybackEngine
from src.queue import Blacklist


class TestObibokBot:
    def _make_bot(self, tmp_path):
        audio = MagicMock()
        audio.play.return_value = True
        audio.stop.return_value = None
        audio.is_playing.return_value = True
        audio.set_collection_volume.return_value = None
        favs = Favorites(str(tmp_path))
        bl = Blacklist(str(tmp_path))
        engine = PlaybackEngine(audio=audio, favorites=favs, blacklist=bl, root_dir=str(tmp_path))
        monitor = MagicMock()
        return ObibokBot(engine=engine, monitor=monitor, root_dir=str(tmp_path))

    def test_bot_creation(self, tmp_path):
        bot = self._make_bot(tmp_path)
        assert bot.engine is not None
        assert bot.monitor is not None

    def test_get_state_creates(self, tmp_path):
        bot = self._make_bot(tmp_path)
        state = bot.get_state(12345)
        assert state.guild_id == 12345
        assert isinstance(state, PlaybackState)

    def test_get_state_reuses(self, tmp_path):
        bot = self._make_bot(tmp_path)
        state1 = bot.get_state(12345)
        state2 = bot.get_state(12345)
        assert state1 is state2

    def test_get_state_different_guilds(self, tmp_path):
        bot = self._make_bot(tmp_path)
        state1 = bot.get_state(111)
        state2 = bot.get_state(222)
        assert state1 is not state2


class TestBotStateManagement:
    def test_state_initialization(self, tmp_path):
        bot = ObibokBot(
            engine=MagicMock(),
            monitor=MagicMock(),
            root_dir=str(tmp_path),
        )
        state = bot.get_state(999)
        assert state.collection_mode == "asma"
        assert state.queue == []
        assert state.is_playing is False
