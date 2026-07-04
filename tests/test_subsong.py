"""Tests for subsong helpers."""

from __future__ import annotations

from src.subsong import subsong_temp_path


def test_subsong_temp_path_is_sanitized(tmp_path):
    path = subsong_temp_path(str(tmp_path), "/music/Some Track!.mod", 2)
    assert path.endswith("Some Track__2.wav")
    assert str(tmp_path / "var" / "subsongs") in path
