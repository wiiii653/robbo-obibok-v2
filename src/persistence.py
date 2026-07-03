"""JSON file I/O for persistence."""

from __future__ import annotations

import json
from pathlib import Path


def load_json(filepath: str | Path) -> dict | list | None:
    try:
        path = Path(filepath)
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def save_json(filepath: str | Path, data: dict | list) -> bool:
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except (OSError, TypeError, ValueError):
        return False


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_tracks_from_cache(cache_path: str | Path) -> list[str] | None:
    data = load_json(cache_path)
    if not isinstance(data, dict):
        return None
    tracks = [t["path"] for t in data.get("tracks", []) if isinstance(t, dict) and "path" in t]
    return tracks if tracks else None
