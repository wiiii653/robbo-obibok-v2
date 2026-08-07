"""Tests for index builder configuration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from index_config import is_junk_path, is_track_file, load_archive_root, save_json_atomic


def test_archive_root_defaults_to_archiwum(tmp_path):
    assert load_archive_root(tmp_path) == tmp_path / "archiwum"


def test_archive_root_uses_configured_path(tmp_path):
    (tmp_path / "config.yaml").write_text("archive:\n  path: music/archive\n")
    assert load_archive_root(tmp_path) == tmp_path / "music" / "archive"


@pytest.mark.parametrize(
    ("relative_path", "contents", "expected_junk"),
    [
        ("._foo.sid", b"fork", True),
        (".DS_Store", b"metadata", True),
        ("desktop.ini", b"metadata", True),
        ("__MACOSX/foo.sid", b"metadata", True),
        ("foo.mod", b"module", False),
        ("foo.txt", b"notes", False),
        ("empty.sid", b"", True),
    ],
)
def test_is_junk_path(tmp_path, relative_path, contents, expected_junk):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)

    assert is_junk_path(path) is expected_junk


def test_is_track_file_requires_allowed_non_junk_nonempty_file(tmp_path):
    good = tmp_path / "good.mod"
    junk = tmp_path / "._fork.mod"
    text = tmp_path / "notes.txt"
    good.write_bytes(b"module")
    junk.write_bytes(b"fork")
    text.write_bytes(b"notes")

    assert is_track_file(good, {"mod"})
    assert not is_track_file(junk, {"mod"})
    assert not is_track_file(text, {"mod"})


def test_save_json_atomic_writes_complete_json_and_removes_temporary_file(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache = {"version": 1, "tracks": [{"path": "music/test.mod", "size": 42}]}

    save_json_atomic(cache_path, cache)

    with cache_path.open(encoding="utf-8") as cache_file:
        assert json.load(cache_file) == cache
    assert not list(tmp_path.glob(".cache.json.*.tmp"))
    assert not (tmp_path / "cache.json.corrupt").exists()
