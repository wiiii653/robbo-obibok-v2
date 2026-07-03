"""Configuration loading — YAML + env overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(slots=True)
class AudioConfig:
    sink_name: str = "robbo_bot"
    sample_rate: int = 48000
    channels: int = 2
    format: str = "s16le"


@dataclass(slots=True)
class PlaybackConfig:
    loop: bool = True
    shuffle: bool = True
    crossfade: int = 0


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

    @property
    def root_dir(self) -> str:
        return str(Path(__file__).resolve().parent.parent)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    root = Path(__file__).resolve().parent.parent
    if config_path is None:
        config_path = root / "config.yaml"

    data: dict = {}
    if Path(config_path).exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    token = os.environ.get("DISCORD_BOT_TOKEN", data.get("token", ""))

    audio_data = data.get("audio", {})
    playback_data = data.get("playback", {})
    auto_data = data.get("auto", {})

    return AppConfig(
        token=token,
        command_prefix=data.get("command_prefix", "!"),
        guild_id=data.get("guild_id"),
        audio=AudioConfig(
            sink_name=audio_data.get("sink_name", "robbo_bot"),
            sample_rate=audio_data.get("sample_rate", 48000),
            channels=audio_data.get("channels", 2),
            format=audio_data.get("format", "s16le"),
        ),
        playback=PlaybackConfig(
            loop=playback_data.get("loop", True),
            shuffle=playback_data.get("shuffle", True),
            crossfade=playback_data.get("crossfade", 0),
        ),
        auto=AutoConfig(
            start_channel=auto_data.get("start_channel", ""),
            empty_timeout=auto_data.get("empty_timeout", 60),
        ),
        archive_path=data.get("archive", {}).get("path", "archiwum"),
    )
