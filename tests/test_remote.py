"""Tests for remote track helpers."""

from __future__ import annotations

from pathlib import Path
from urllib.error import URLError

from src.remote import (
    download_remote_track,
    is_allowed_remote_url,
    is_remote_track,
    remote_cache_path,
)


def test_is_remote_track():
    assert is_remote_track("https://example.com/song.mod") is True
    assert is_remote_track("http://example.com/song.mod") is True
    assert is_remote_track("/music/song.mod") is False
    assert is_remote_track("https://") is False
    assert is_remote_track("file:///music/song.mod") is False


def test_is_remote_track_rejects_malformed_url():
    assert is_remote_track("https://[invalid") is False


def test_remote_url_policy_enforces_allowlist_and_rejects_private_ips(monkeypatch):
    monkeypatch.setattr(
        "src.remote.socket.getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, "", ("93.184.216.34", 0))],
    )
    assert is_allowed_remote_url("https://example.com/song.mod", ("example.com",)) is True
    assert is_allowed_remote_url("https://evil.example/song.mod", ("example.com",)) is False
    assert is_allowed_remote_url("http://127.0.0.1/song.mod") is False
    assert is_allowed_remote_url("http://[::1]/song.mod") is False


def test_remote_cache_path_is_stable_and_sanitized(tmp_path):
    path1 = remote_cache_path(str(tmp_path), "https://example.com/a/b/My Track!.mod")
    path2 = remote_cache_path(str(tmp_path), "https://example.com/a/b/My Track!.mod")
    assert path1 == path2
    assert Path(path1).parent == tmp_path / "var" / "downloads"
    assert "My Track" in Path(path1).name


def test_download_remote_track_writes_file(tmp_path, monkeypatch):
    class FakeResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int) -> bytes:
            data, self._data = self._data[:size], self._data[size:]
            return data

    def fake_urlopen(request, timeout=0):
        return FakeResponse(b"abc123")

    monkeypatch.setattr("src.remote.urlopen", fake_urlopen)
    output = tmp_path / "out.mod"
    result = download_remote_track("https://example.com/out.mod", str(output))
    assert result == str(output)
    assert output.read_bytes() == b"abc123"


def test_download_remote_track_reuses_nonempty_cache(tmp_path, monkeypatch):
    output = tmp_path / "cached.mod"
    output.write_bytes(b"already-downloaded")

    def unexpected_urlopen(*args, **kwargs):
        raise AssertionError("cache hit must not access the network")

    monkeypatch.setattr("src.remote.urlopen", unexpected_urlopen)
    result = download_remote_track("https://example.com/cached.mod", str(output))
    assert result == str(output)
    assert output.read_bytes() == b"already-downloaded"


def test_download_remote_track_retries_transient_network_failure(tmp_path, monkeypatch):
    attempts = 0

    class FakeResponse:
        def __init__(self):
            self.remaining = b"ok"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int) -> bytes:
            data, self.remaining = self.remaining[:size], self.remaining[size:]
            return data

    def flaky_urlopen(request, timeout=0):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise URLError("temporary failure")
        return FakeResponse()

    monkeypatch.setattr("src.remote.urlopen", flaky_urlopen)
    monkeypatch.setattr("src.remote.time.sleep", lambda _: None)
    output = tmp_path / "retry.mod"

    assert download_remote_track("https://example.com/retry.mod", str(output)) == str(output)
    assert attempts == 3
