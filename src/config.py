"""Configuration loading — YAML + env overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(slots=True)
class AudioConfig:
    sink_name: str = "robbo_bot"


@dataclass(slots=True)
class PlaybackConfig:
    loop: bool = False
    shuffle: bool = True


@dataclass(slots=True)
class AutoConfig:
    start_channel: str = ""
    empty_timeout: int = 60


@dataclass(slots=True)
class AppConfig:
    token: str = ""
    command_prefix: str = "!"
    guild_id: int | None = None
    audio: AudioConfig = field(default_factory=AudioConfig)
    playback: PlaybackConfig = field(default_factory=PlaybackConfig)
    auto: AutoConfig = field(default_factory=AutoConfig)
    archive_path: str = "archiwum"
    format_volumes: dict[str, int] = field(default_factory=dict)

    @property
    def root_dir(self) -> str:
        return str(Path(__file__).resolve().parent.parent)


def _require_mapping(data: dict, key: str) -> dict:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"config.{key} must be a mapping")
    return value


def validate_config(data: dict) -> None:
    if "token" in data:
        raise ValueError("config.token is not supported; set DISCORD_BOT_TOKEN in the environment")

    if not isinstance(data.get("command_prefix", "!"), str) or not data.get("command_prefix", "!"):
        raise ValueError("config.command_prefix must not be empty")

    guild_id = data.get("guild_id")
    if guild_id is not None and (
        not isinstance(guild_id, int) or isinstance(guild_id, bool) or guild_id <= 0
    ):
        raise ValueError("config.guild_id must be a positive integer")

    if "audio" in data:
        audio = _require_mapping(data, "audio")
        sink_name = audio.get("sink_name", "robbo_bot")
        if "sink_name" in audio and (not isinstance(sink_name, str) or not sink_name):
            raise ValueError("config.audio.sink_name must be a non-empty string")

    if "playback" in data:
        playback = _require_mapping(data, "playback")
        if "loop" in playback and not isinstance(playback.get("loop"), bool):
            raise ValueError("config.playback.loop must be a boolean")
        if "shuffle" in playback and not isinstance(playback.get("shuffle"), bool):
            raise ValueError("config.playback.shuffle must be a boolean")

    if "auto" in data:
        auto = _require_mapping(data, "auto")
        if "start_channel" in auto and not isinstance(auto.get("start_channel"), str):
            raise ValueError("config.auto.start_channel must be a string")
        if "empty_timeout" in auto:
            empty_timeout = auto.get("empty_timeout", 60)
            if (
                not isinstance(empty_timeout, int)
                or isinstance(empty_timeout, bool)
                or empty_timeout < 0
            ):
                raise ValueError("config.auto.empty_timeout must be zero or greater")

    if "archive" in data:
        archive = _require_mapping(data, "archive")
        archive_path = archive.get("path", "archiwum")
        archive_parts = Path(archive_path).parts if isinstance(archive_path, str) else ()
        if "path" in archive and (
            not isinstance(archive_path, str)
            or not archive_path
            or Path(archive_path).is_absolute()
            or ".." in archive_parts
        ):
            raise ValueError("config.archive.path must be a non-empty string")

    if "format_volumes" in data:
        volumes = data["format_volumes"]
        if not isinstance(volumes, dict):
            raise ValueError("config.format_volumes must be a mapping")
        for extension, volume in volumes.items():
            if (
                not isinstance(extension, str)
                or not extension
                or not isinstance(volume, int)
                or isinstance(volume, bool)
                or not 0 <= volume <= 200
            ):
                raise ValueError(
                    "config.format_volumes values must map non-empty extensions to integers from 0 to 200"
                )


def load_config(config_path: str | Path | None = None) -> AppConfig:
    root = Path(__file__).resolve().parent.parent
    if config_path is None:
        config_path = root / "config.yaml"

    data: dict = {}
    if Path(config_path).exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a mapping at the top level")

    validate_config(data)

    token = os.environ.get("DISCORD_BOT_TOKEN", "")

    audio_data = _require_mapping(data, "audio")
    playback_data = _require_mapping(data, "playback")
    auto_data = _require_mapping(data, "auto")
    archive_data = _require_mapping(data, "archive")
    format_volumes = data.get("format_volumes", {})

    return AppConfig(
        token=token,
        command_prefix=data.get("command_prefix", "!"),
        guild_id=data.get("guild_id"),
        audio=AudioConfig(
            sink_name=audio_data.get("sink_name", "robbo_bot"),
        ),
        playback=PlaybackConfig(
            loop=playback_data.get("loop", False),
            shuffle=playback_data.get("shuffle", True),
        ),
        auto=AutoConfig(
            start_channel=auto_data.get("start_channel", ""),
            empty_timeout=auto_data.get("empty_timeout", 60),
        ),
        archive_path=archive_data.get("path", "archiwum"),
        format_volumes=dict(format_volumes),
    )
