"""Tests for config module."""

from __future__ import annotations

from src.config import AppConfig, AudioConfig, AutoConfig, PlaybackConfig, load_config


class TestAppConfig:
    def test_default_config(self):
        config = AppConfig()
        assert config.command_prefix == "!"
        assert config.guild_id is None
        assert config.audio.sink_name == "robbo_bot"
        assert config.playback.loop is True
        assert config.playback.shuffle is True
        assert config.auto.empty_timeout == 60

    def test_root_dir(self):
        config = AppConfig()
        assert "robbo-obibok-v2" in config.root_dir


class TestLoadConfig:
    def test_load_default(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("command_prefix: '?'\n")
        config = load_config(config_path)
        assert config.command_prefix == "?"

    def test_load_with_audio(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("audio:\n  sink_name: test_sink\n")
        config = load_config(config_path)
        assert config.audio.sink_name == "test_sink"

    def test_load_with_playback(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("playback:\n  loop: false\n  shuffle: false\n")
        config = load_config(config_path)
        assert config.playback.loop is False
        assert config.playback.shuffle is False

    def test_load_with_auto(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("auto:\n  start_channel: Radio\n  empty_timeout: 120\n")
        config = load_config(config_path)
        assert config.auto.start_channel == "Radio"
        assert config.auto.empty_timeout == 120

    def test_load_with_guild_id(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("guild_id: 123456789\n")
        config = load_config(config_path)
        assert config.guild_id == 123456789

    def test_load_nonexistent(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.command_prefix == "!"

    def test_env_token_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        config = load_config()
        assert config.token == "test-token"


class TestAudioConfig:
    def test_defaults(self):
        audio = AudioConfig()
        assert audio.sink_name == "robbo_bot"
        assert audio.sample_rate == 48000
        assert audio.channels == 2


class TestPlaybackConfig:
    def test_defaults(self):
        playback = PlaybackConfig()
        assert playback.loop is True
        assert playback.shuffle is True
        assert playback.crossfade == 0


class TestAutoConfig:
    def test_defaults(self):
        auto = AutoConfig()
        assert auto.start_channel == ""
        assert auto.empty_timeout == 60
