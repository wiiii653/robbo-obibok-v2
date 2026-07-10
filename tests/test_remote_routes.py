"""Tests for source-specific remote routing."""

from __future__ import annotations

from pathlib import Path

from src.remote import download_modarchive_module, uses_module_cache


def test_module_cache_detection():
    assert uses_module_cache("https://example.com/song.sid") is False
    assert uses_module_cache("https://example.com/moduleid=123") is True
    assert uses_module_cache("https://example.com/song.MOD?download=1") is True


def test_download_modarchive_module_uses_cache(tmp_path, monkeypatch):
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
        return FakeResponse(b"module-bytes")

    monkeypatch.setattr("src.remote.urlopen", fake_urlopen)
    path = download_modarchive_module("https://example.com/?moduleid=77", root_dir=str(tmp_path))
    assert Path(path).exists()
    assert Path(path).read_bytes() == b"module-bytes"
