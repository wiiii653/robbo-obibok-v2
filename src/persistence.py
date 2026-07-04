"""JSON file I/O for persistence."""

from __future__ import annotations

import json
import os
import tempfile
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
    temp_path: str | None = None
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def load_tracks_from_cache(cache_path: str | Path) -> list[str] | None:
    data = load_json(cache_path)
    if not isinstance(data, dict):
        return None
    tracks = [t["path"] for t in data.get("tracks", []) if isinstance(t, dict) and "path" in t]
    return tracks if tracks else None
