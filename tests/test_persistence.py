"""Tests for persistence module."""

from __future__ import annotations

import json

from src.persistence import load_json, load_tracks_from_cache, save_json


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
        backups = list(tmp_path.glob("invalid.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text() == "not json {{{"


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

    def test_save_and_load_create_lock_file(self, tmp_path):
        filepath = tmp_path / "locked.json"
        assert save_json(filepath, {"ok": True}) is True
        assert load_json(filepath) == {"ok": True}
        assert (tmp_path / ".locked.json.lock").exists()


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
