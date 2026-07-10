"""Tests for config module."""

from __future__ import annotations

import pytest

from src.config import AppConfig, AudioConfig, AutoConfig, PlaybackConfig, load_config


class TestAppConfig:
    def test_default_config(self):
        config = AppConfig()
        assert config.command_prefix == "!"
        assert config.guild_id is None
        assert config.audio.sink_name == "robbo_bot"
        assert config.playback.loop is False
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

    def test_token_in_yaml_is_rejected(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("token: secret\n")
        with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
            load_config(config_path)

    @pytest.mark.parametrize("path", ["/var/lib/robbo/archive", "../archive", "foo/../../archive"])
    def test_archive_path_must_stay_relative(self, tmp_path, path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(f"archive:\n  path: {path}\n")
        with pytest.raises(ValueError, match="archive.path"):
            load_config(config_path)

    def test_format_volumes_are_loaded_and_validated(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("format_volumes:\n  sid: 120\n")
        config = load_config(config_path)
        assert config.format_volumes == {"sid": 120}

    def test_format_volume_out_of_range_is_rejected(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("format_volumes:\n  sid: 201\n")
        with pytest.raises(ValueError, match="format_volumes"):
            load_config(config_path)

    def test_remote_allowlist_is_loaded(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("remote:\n  allowed_domains: [example.com, YouTube.com]\n")
        config = load_config(config_path)
        assert config.remote.allowed_domains == ("example.com", "youtube.com")

    def test_remote_allowlist_rejects_invalid_hostnames(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("remote:\n  allowed_domains: ['not a host']\n")
        with pytest.raises(ValueError, match="allowed_domains"):
            load_config(config_path)

    def test_allows_sparse_config(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("command_prefix: '?'\n")
        config = load_config(config_path)
        assert config.command_prefix == "?"


class TestAudioConfig:
    def test_defaults(self):
        audio = AudioConfig()
        assert audio.sink_name == "robbo_bot"


class TestPlaybackConfig:
    def test_defaults(self):
        playback = PlaybackConfig()
        assert playback.loop is False
        assert playback.shuffle is True


class TestAutoConfig:
    def test_defaults(self):
        auto = AutoConfig()
        assert auto.start_channel == ""
        assert auto.empty_timeout == 60
