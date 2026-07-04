"""Favorites system — reaction-based favorites + named playlists."""

from __future__ import annotations

import time
from pathlib import Path

from .persistence import load_json, save_json


def _normalize_track_entry(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    filepath = entry.get("filepath")
    if not isinstance(filepath, str) or not filepath:
        return None
    title = entry.get("title", "")
    collection_id = entry.get("collection_id", "")
    added_at = entry.get("added_at", 0.0)
    if not isinstance(title, str):
        title = ""
    if not isinstance(collection_id, str):
        collection_id = ""
    if not isinstance(added_at, (int, float)) or isinstance(added_at, bool):
        added_at = 0.0
    return {
        "filepath": filepath,
        "title": title,
        "collection_id": collection_id,
        "added_at": float(added_at),
    }


def _normalize_playlist_record(data: object) -> dict | None:
    if not isinstance(data, dict):
        return None
    tracks = data.get("tracks", [])
    if not isinstance(tracks, list):
        return None
    normalized_tracks = [item for item in (_normalize_track_entry(track) for track in tracks) if item]
    return {
        "name": data.get("name", ""),
        "author": data.get("author", ""),
        "author_id": data.get("author_id", 0),
        "created": data.get("created", 0),
        "tracks": normalized_tracks,
    }


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
            normalized: dict[str, list[dict]] = {}
            for key, value in raw.items():
                if not isinstance(value, list):
                    continue
                tracks = [item for item in (_normalize_track_entry(entry) for entry in value) if item]
                normalized[key] = tracks
            self._data = normalized
        self._loaded = True

    def _save(self) -> None:
        save_json(self._filepath, self._data)

    def toggle(self, user_id: int, filepath: str, title: str = "", collection_id: str = "") -> bool:
        if self.has_track(user_id, filepath, collection_id):
            self.remove(user_id, filepath, collection_id)
            return False
        self.add(user_id, filepath, title, collection_id)
        return True

    def add(self, user_id: int, filepath: str, title: str = "", collection_id: str = "") -> bool:
        self._ensure_loaded()
        uid = str(user_id)
        tracks = self._data.setdefault(uid, [])
        if self.has_track(user_id, filepath, collection_id):
            return False
        tracks.append({
            "filepath": filepath,
            "title": title,
            "collection_id": collection_id,
            "added_at": time.time(),
        })
        self._save()
        return True

    def remove(self, user_id: int, filepath: str, collection_id: str = "") -> bool:
        self._ensure_loaded()
        tracks = self._data.get(str(user_id), [])
        existing = next(
            (
                track
                for track in tracks
                if track.get("filepath") == filepath
                and (not collection_id or track.get("collection_id", "") == collection_id)
            ),
            None,
        )
        if existing is None:
            return False
        tracks.remove(existing)
        self._save()
        return True

    def get_tracks(self, user_id: int) -> list[dict]:
        self._ensure_loaded()
        return list(self._data.get(str(user_id), []))

    def has_track(self, user_id: int, filepath: str, collection_id: str = "") -> bool:
        self._ensure_loaded()
        tracks = self._data.get(str(user_id), [])
        return any(
            track.get("filepath") == filepath
            and (not collection_id or track.get("collection_id", "") == collection_id)
            for track in tracks
        )

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
            normalized = _normalize_playlist_record(result)
            if normalized is not None:
                return normalized
        return None

    def list_playlists(self) -> list[dict]:
        playlists: list[dict] = []
        for filepath in sorted(self._dir.glob("*.json")):
            data = load_json(filepath)
            normalized = _normalize_playlist_record(data)
            if not normalized:
                continue
            playlists.append({
                "name": normalized.get("name", filepath.stem) or filepath.stem,
                "author": normalized.get("author", "?") or "?",
                "tracks": len(normalized.get("tracks", [])),
                "created": normalized.get("created", 0),
            })
        return playlists

    def delete(self, name: str) -> bool:
        safe = self._safe_name(name)
        filepath = self._dir / f"{safe}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False
