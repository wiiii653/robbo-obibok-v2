"""Tests for remote playback integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from src.favorites import Favorites
from src.models import PlaybackState
from src.playback import PlaybackEngine
from src.queue import Blacklist
from src.remote import remote_cache_path


def _make_engine(tmp_path):
    audio = MagicMock()
    audio.play.return_value = True
    audio.stop.return_value = None
    favs = Favorites(str(tmp_path))
    bl = Blacklist(str(tmp_path))
    return PlaybackEngine(audio=audio, favorites=favs, blacklist=bl, root_dir=str(tmp_path))


def test_remote_track_is_downloaded_before_play(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path)
    state = PlaybackState(queue=["https://example.com/song.mod"], position=0)
    expected_path = remote_cache_path(str(tmp_path), "https://example.com/song.mod")

    async def fake_download(state, track):
        path = Path(expected_path)
        path.write_bytes(b"music")
        return str(path)

    engine._download_remote_track = fake_download  # type: ignore[assignment]
    engine._prepare_subsong_playback = lambda state, path: path  # type: ignore[assignment]

    async def immediate(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("src.playback.asyncio.to_thread", immediate)

    played = asyncio.run(engine.play_track(state))

    assert played == "https://example.com/song.mod"
    assert engine.audio.play.called
    assert engine.audio.play.call_args[0][0] == expected_path
    assert state.current_track == "https://example.com/song.mod"
    assert state.predownload_url == ""
    assert state.predownload_path == ""


def test_predownload_next_caches_remote_track(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path)
    state = PlaybackState(queue=["local.sap", "https://example.com/next.mod"], position=0)

    async def fake_download(state, track):
        path = tmp_path / "var" / "downloads" / "next.mod"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"music")
        return str(path)

    engine._download_remote_track = fake_download  # type: ignore[assignment]

    async def immediate(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("src.playback.asyncio.to_thread", immediate)

    cached = asyncio.run(engine.predownload_next(state))

    assert cached is not None
    assert state.predownload_url == "https://example.com/next.mod"
    assert state.predownload_path == cached


def test_predownload_loop_targets_next_track(tmp_path):
    engine = _make_engine(tmp_path)
    current = "https://example.com/current.mod"
    next_t = "https://example.com/next.mod"
    state = PlaybackState(
        queue=[current, next_t],
        position=0,
        is_looping=True,
    )
    downloaded = []

    async def fake_download(state, track):
        downloaded.append(track)
        path = tmp_path / "next.mod"
        path.write_bytes(b"music")
        return str(path)

    engine._download_remote_track = fake_download  # type: ignore[assignment]
    asyncio.run(engine.predownload_next(state))
    assert downloaded == [next_t]  # now predownloads next track, not current
