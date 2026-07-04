"""Tests for index builder configuration."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from index_config import load_archive_root


def test_archive_root_defaults_to_archiwum(tmp_path):
    assert load_archive_root(tmp_path) == tmp_path / "archiwum"


def test_archive_root_uses_configured_path(tmp_path):
    (tmp_path / "config.yaml").write_text("archive:\n  path: music/archive\n")
    assert load_archive_root(tmp_path) == tmp_path / "music" / "archive"
