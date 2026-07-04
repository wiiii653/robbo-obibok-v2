"""Core domain models for Robbo Obibok v2."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Collection:
    id: str
    name: str
    extensions: list[str]
    archive_path: str
    cache_file: str
    volume: int = 100
    flip_tag: str = ""
    icon: str = ""
    footer: str = ""


FLIP_ORDER: list[str] = ["hvsc", "asma", "modarchive", "ay", "ym", "tiny", "kgen"]

COLLECTIONS: dict[str, Collection] = {
    "hvsc": Collection(
        id="hvsc",
        name="C64 SID (HVSC)",
        extensions=["sid"],
        archive_path="hvsc/C64Music",
        cache_file="hvsc_cache_local.json",
        volume=120,
        flip_tag="🟣HVSC",
        icon="🟣",
        footer="C64 SID Radio",
    ),
    "asma": Collection(
        id="asma",
        name="Atari SAP (ASMA)",
        extensions=["sap"],
        archive_path="asma",
        cache_file="asma_cache_local.json",
        volume=100,
        flip_tag="🟢ASMA",
        icon="🟢",
        footer="ASMA Radio",
    ),
    "modarchive": Collection(
        id="modarchive",
        name="Tracker Modules (ModArchive)",
        extensions=["mod", "xm", "s3m", "it"],
        archive_path="modarchive",
        cache_file="modarchive_cache_local.json",
        volume=100,
        flip_tag="🟠Mod",
        icon="🟠",
        footer="ModArchive Radio",
    ),
    "ay": Collection(
        id="ay",
        name="ZX Spectrum AY",
        extensions=["ay"],
        archive_path="ay",
        cache_file="ay_cache_local.json",
        volume=100,
        flip_tag="🔵AY",
        icon="🔵",
        footer="ZX Spectrum Radio",
    ),
    "ym": Collection(
        id="ym",
        name="Atari ST YM",
        extensions=["ym"],
        archive_path="ym",
        cache_file="ym_cache_local.json",
        volume=100,
        flip_tag="🎹YM",
        icon="🎹",
        footer="Atari ST YM Radio",
    ),
    "tiny": Collection(
        id="tiny",
        name="Tiny Music (Demoscene)",
        extensions=["mod", "xm", "it", "s3m", "med", "dmf"],
        archive_path="tiny",
        cache_file="tiny_cache_local.json",
        volume=100,
        flip_tag="🎵Tiny",
        icon="🎵",
        footer="Tiny Music Radio",
    ),
    "kgen": Collection(
        id="kgen",
        name="Keygen Music",
        extensions=["mod", "xm", "it", "s3m"],
        archive_path="kgen",
        cache_file="kgen_cache_local.json",
        volume=100,
        flip_tag="🔊KGen",
        icon="🔊",
        footer="Keygen Music Radio",
    ),
}


@dataclass(slots=True)
class PlaybackState:
    guild_id: int = 0
    collection_mode: str = "asma"
    tracks: list[str] = field(default_factory=list)
    queue: list[str] = field(default_factory=list)
    queue_collection_ids: list[str] = field(default_factory=list)
    position: int = 0
    current_track: str = ""
    current_collection_id: str = ""
    is_playing: bool = False
    is_looping: bool = False
    voice_channel_id: int | None = None
    history: list[str] = field(default_factory=list)
    played_count: int = 0
    search_results: list[str] = field(default_factory=list)
    search_collection_id: str = ""
    subsong_path: str = ""
    subsong_current: int = -1
    subsong_total: int = 0
    subsong_wavs: list[str] = field(default_factory=list)
    predownload_path: str = ""
    predownload_url: str = ""
