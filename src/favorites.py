"""Favorites system — reaction-based favorites + named playlists."""

from __future__ import annotations

import time
from pathlib import Path

from .persistence import load_json, save_json


class Favorites:
    def __init__(self, root_dir: str) -> None:
        self._filepath = Path(root_dir) / "favorites.json"
        self._data: dict[str, list[dict]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        raw = load_json(self._filepath)
        if isinstance(raw, dict):
            self._data = {k: v for k, v in raw.items() if isinstance(v, list)}
        self._loaded = True

    def _save(self) -> None:
        save_json(self._filepath, self._data)

    def toggle(self, user_id: int, filepath: str, title: str = "", collection_id: str = "") -> bool:
        self._ensure_loaded()
        uid = str(user_id)
        tracks = self._data.setdefault(uid, [])
        existing = next((t for t in tracks if t.get("filepath") == filepath), None)
        if existing:
            tracks.remove(existing)
            self._save()
            return False
        tracks.append({
            "filepath": filepath,
            "title": title,
            "collection_id": collection_id,
            "added_at": time.time(),
        })
        self._save()
        return True

    def get_tracks(self, user_id: int) -> list[dict]:
        self._ensure_loaded()
        return list(self._data.get(str(user_id), []))

    def has_track(self, user_id: int, filepath: str) -> bool:
        self._ensure_loaded()
        tracks = self._data.get(str(user_id), [])
        return any(t.get("filepath") == filepath for t in tracks)

    def count(self, user_id: int) -> int:
        self._ensure_loaded()
        return len(self._data.get(str(user_id), []))


class PlaylistLibrary:
    def __init__(self, root_dir: str) -> None:
        self._dir = Path(root_dir) / "var" / "playlists"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, name: str) -> str:
        safe = "".join(c if c.isalnum() or c in " _-." else "_" for c in name)
        return safe.strip().strip(".") or "unnamed"

    def save(
        self,
        name: str,
        tracks: list[dict],
        author_id: int,
        author_name: str,
    ) -> str:
        safe = self._safe_name(name)
        filepath = self._dir / f"{safe}.json"
        data = {
            "name": name,
            "author": author_name,
            "author_id": author_id,
            "created": time.time(),
            "tracks": tracks,
        }
        save_json(filepath, data)
        return safe

    def load(self, name: str) -> dict | None:
        safe = self._safe_name(name)
        for ext in ("", ".json"):
            filepath = self._dir / f"{safe}{ext}"
            result = load_json(filepath)
            if result is not None:
                return result
        return None

    def list_playlists(self) -> list[dict]:
        playlists: list[dict] = []
        for filepath in sorted(self._dir.glob("*.json")):
            data = load_json(filepath)
            if not isinstance(data, dict):
                continue
            playlists.append({
                "name": data.get("name", filepath.stem),
                "author": data.get("author", "?"),
                "tracks": len(data.get("tracks", [])),
                "created": data.get("created", 0),
            })
        return playlists

    def delete(self, name: str) -> bool:
        safe = self._safe_name(name)
        filepath = self._dir / f"{safe}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False
