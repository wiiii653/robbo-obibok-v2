"""Tests for persistence module."""

from __future__ import annotations

import json

from src.persistence import ensure_dir, load_json, load_tracks_from_cache, save_json


class TestLoadJson:
    def test_load_valid_json(self, tmp_path):
        data = {"key": "value", "number": 42}
        filepath = tmp_path / "test.json"
        filepath.write_text(json.dumps(data))
        result = load_json(filepath)
        assert result == data

    def test_load_nonexistent(self, tmp_path):
        result = load_json(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_invalid_json(self, tmp_path):
        filepath = tmp_path / "invalid.json"
        filepath.write_text("not json {{{")
        result = load_json(filepath)
        assert result is None


class TestSaveJson:
    def test_save_and_load(self, tmp_path):
        data = {"tracks": [{"path": "a.sap"}, {"path": "b.sid"}]}
        filepath = tmp_path / "output.json"
        assert save_json(filepath, data) is True
        loaded = load_json(filepath)
        assert loaded == data

    def test_save_creates_directories(self, tmp_path):
        data = {"test": True}
        filepath = tmp_path / "sub" / "dir" / "file.json"
        assert save_json(filepath, data) is True
        assert filepath.exists()


class TestLoadTracksFromCache:
    def test_load_tracks(self, tmp_path):
        cache = {
            "version": 1,
            "tracks": [{"path": "a.sap"}, {"path": "b.sap"}],
        }
        filepath = tmp_path / "cache.json"
        filepath.write_text(json.dumps(cache))
        tracks = load_tracks_from_cache(filepath)
        assert tracks == ["a.sap", "b.sap"]

    def test_load_empty_tracks(self, tmp_path):
        cache = {"tracks": []}
        filepath = tmp_path / "cache.json"
        filepath.write_text(json.dumps(cache))
        assert load_tracks_from_cache(filepath) is None

    def test_load_nonexistent(self, tmp_path):
        assert load_tracks_from_cache(tmp_path / "nope.json") is None


class TestEnsureDir:
    def test_creates_directory(self, tmp_path):
        new_dir = tmp_path / "new" / "nested" / "dir"
        result = ensure_dir(new_dir)
        assert result.exists()
        assert result.is_dir()
