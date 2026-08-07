"""Security regression tests for the archive and module grabbers."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import download_modarchive_bulk
import fetch_archives
import fetch_pouet_mods


def test_manifest_traversal_entries_are_not_planned(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_pouet_mods, "_validate_download_url", lambda _url: None)
    manifest = {
        "artists": [
            {"name": "../evil", "files": ["song.mod"]},
            {"name": "artist", "subdir": "../x", "files": ["song.mod"]},
        ],
        "direct": [{"url": "https://archive.org/file.mod", "dest": "/abs/file.mod"}],
    }
    messages: list[str] = []

    assert fetch_pouet_mods.run_manifest(manifest, tmp_path, 1, True, False, messages.append) == 0
    assert not (tmp_path.parent / "evil").exists()
    assert any("niebezpieczna ścieżka" in message for message in messages)
    assert any("'/abs/file.mod'" in message for message in messages)


@pytest.mark.parametrize("url", ["http://127.0.0.1/file.mod", "file:///tmp/file.mod"])
def test_pouet_http_rejects_private_and_non_http_urls(url):
    with pytest.raises(ValueError):
        fetch_pouet_mods._validate_download_url(url)


@pytest.mark.parametrize(
    "member_block",
    [
        "Path = ../escape.mod\nSize = 1\nAttributes = A_ -rw-r--r--",
        "Path = /absolute.mod\nSize = 1\nAttributes = A_ -rw-r--r--",
        "Path = linked.mod\nSize = 1\nAttributes = A_ lrwxrwxrwx\nSymbolic Link = target",
    ],
)
def test_extract_rejects_unsafe_7z_members(tmp_path, monkeypatch, member_block):
    calls: list[list[str]] = []
    listing = f"Path = archive.7z\nType = 7z\n----------\n{member_block}\n\n"

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[1] == "l":
            return subprocess.CompletedProcess(cmd, 0, stdout=listing, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(fetch_archives.subprocess, "run", fake_run)

    assert not fetch_archives.extract(tmp_path / "archive.7z", tmp_path / "out")
    assert [call[1] for call in calls] == ["l"]


@pytest.mark.parametrize("version", ["abc", "1/2"])
def test_hvsc_plan_rejects_invalid_versions(tmp_path, monkeypatch, version):
    monkeypatch.setattr(fetch_archives, "ARCHIVIUM", tmp_path)
    monkeypatch.setattr(
        fetch_archives, "http_get", lambda _url: f'{{"version": "{version}"}}'.encode()
    )

    assert fetch_archives.hvsc_plan() == {}


def test_hvsc_plan_accepts_numeric_version(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_archives, "ARCHIVIUM", tmp_path)
    monkeypatch.setattr(fetch_archives, "http_get", lambda _url: b'{"version": "85"}')

    plan = fetch_archives.hvsc_plan()

    assert plan["version"] == "85"
    assert plan["dest"] == tmp_path / "hvsc"
    assert plan["complete_url"].endswith("HVSC_85-all-of-them.7z")


def test_modarchive_zip_is_safely_extracted_and_removed(tmp_path):
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("nested/song.mod", b"module")
        zip_file.writestr("__MACOSX/metadata", b"metadata")

    assert download_modarchive_bulk.extract_zip(archive)
    assert (tmp_path / "bundle" / "nested" / "song.mod").read_bytes() == b"module"
    assert not (tmp_path / "bundle" / "__MACOSX").exists()
    assert not archive.exists()


def test_modarchive_zip_rejects_traversal_member(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../escape.mod", b"module")

    assert not download_modarchive_bulk.extract_zip(archive)
    assert archive.exists()
    assert not (tmp_path.parent / "escape.mod").exists()
