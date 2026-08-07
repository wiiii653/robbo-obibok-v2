"""Favorites system — reaction-based favorites + named playlists."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .persistence import is_safe_track_path, load_json, save_json

FAVORITES_SCHEMA_VERSION = 2
PLAYLIST_SCHEMA_VERSION = 2
MAX_FAVORITES_TOTAL_ENTRIES = 100_000
MAX_FAVORITES_ENTRIES_PER_USER = 50_000

logger = logging.getLogger(__name__)


def _normalize_track_entry(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    filepath = entry.get("filepath")
    if not is_safe_track_path(filepath):
        return None
    title = entry.get("title", "")
    author = entry.get("author", "")
    collection_id = entry.get("collection_id", "")
    added_at = entry.get("added_at", 0.0)
    if not isinstance(title, str):
        title = ""
    if not isinstance(author, str):
        author = ""
    if not isinstance(collection_id, str):
        collection_id = ""
    if not isinstance(added_at, (int, float)) or isinstance(added_at, bool):
        added_at = 0.0
    return {
        "filepath": filepath,
        "title": title,
        "author": author,
        "collection_id": collection_id,
        "added_at": float(added_at),
    }


def _normalize_playlist_record(data: object) -> dict | None:
    if not isinstance(data, dict):
        return None
    schema_version = data.get("schema_version", 1)
    if schema_version not in (1, PLAYLIST_SCHEMA_VERSION):
        return None
    tracks = data.get("tracks", [])
    if not isinstance(tracks, list):
        return None
    normalized_tracks = [
        item for item in (_normalize_track_entry(track) for track in tracks) if item
    ]
    return {
        "schema_version": schema_version,
        "name": data.get("name", ""),
        "author": data.get("author", ""),
        "author_id": data.get("author_id", 0),
        "created": data.get("created", 0),
        "tracks": normalized_tracks,
    }


class Favorites:
    def __init__(self, root_dir: str) -> None:
        self._root_dir = Path(root_dir)
        self._filepath = Path(root_dir) / "favorites.json"
        self._data: dict[str, list[dict]] = {}
        self._filepath_sets: dict[str, set[str]] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    async def _run_locked(self, method, *args):
        """Run persistence-backed operations off the event loop serially."""
        async with self._lock:
            return await asyncio.to_thread(method, *args)

    async def async_toggle(
        self,
        user_id: int,
        filepath: str,
        title: str = "",
        collection_id: str = "",
        author: str = "",
    ) -> bool:
        return await self._run_locked(self.toggle, user_id, filepath, title, collection_id, author)

    async def async_add(
        self,
        user_id: int,
        filepath: str,
        title: str = "",
        collection_id: str = "",
        author: str = "",
    ) -> bool:
        return await self._run_locked(self.add, user_id, filepath, title, collection_id, author)

    async def async_remove(self, user_id: int, filepath: str) -> bool:
        return await self._run_locked(self.remove, user_id, filepath)

    async def async_get_tracks(self, user_id: int) -> list[dict]:
        return await self._run_locked(self.get_tracks, user_id)

    async def async_set_track_metadata(
        self, user_id: int, filepath: str, title: str, author: str = ""
    ) -> bool:
        return await self._run_locked(self.set_track_metadata, user_id, filepath, title, author)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        raw = load_json(self._filepath, root_dir=self._root_dir)
        if isinstance(raw, dict):
            raw_lists = [value for value in raw.values() if isinstance(value, list)]
            total_entries = sum(len(value) for value in raw_lists)
            oversized_user = any(len(value) > MAX_FAVORITES_ENTRIES_PER_USER for value in raw_lists)
            if total_entries > MAX_FAVORITES_TOTAL_ENTRIES or oversized_user:
                logger.warning(
                    "Skipping oversized favorites file %s (%d entries)",
                    self._filepath,
                    total_entries,
                )
                self._loaded = True
                return
            normalized: dict[str, list[dict]] = {}
            for key, value in raw.items():
                if not isinstance(value, list):
                    continue
                tracks = [
                    item for item in (_normalize_track_entry(entry) for entry in value) if item
                ]
                # Dedup by filepath — keep last entry per unique filepath
                seen: set[str] = set()
                deduped: list[dict] = []
                for t in reversed(tracks):
                    fp = t.get("filepath", "")
                    if fp and fp not in seen:
                        seen.add(fp)
                        deduped.append(t)
                deduped.reverse()
                normalized[key] = deduped
            self._data = normalized
            self._filepath_sets = {
                key: {track["filepath"] for track in tracks} for key, tracks in normalized.items()
            }
        self._loaded = True

    def _save(self) -> None:
        save_json(
            self._filepath,
            {"schema_version": FAVORITES_SCHEMA_VERSION, **self._data},
            root_dir=self._root_dir,
        )

    def _track_index(self, user_id: int, filepath: str) -> int | None:
        self._ensure_loaded()
        uid = str(user_id)
        if filepath not in self._filepath_sets.get(uid, set()):
            return None
        tracks = self._data.get(uid, [])
        for index, track in enumerate(tracks):
            if track.get("filepath") == filepath:
                return index
        return None

    def toggle(
        self,
        user_id: int,
        filepath: str,
        title: str = "",
        collection_id: str = "",
        author: str = "",
    ) -> bool:
        if self._track_index(user_id, filepath) is not None:
            self.remove(user_id, filepath)
            return False
        self.add(user_id, filepath, title, collection_id, author)
        return True

    def add(
        self,
        user_id: int,
        filepath: str,
        title: str = "",
        collection_id: str = "",
        author: str = "",
    ) -> bool:
        index = self._track_index(user_id, filepath)
        uid = str(user_id)
        tracks = self._data.setdefault(uid, [])
        self._filepath_sets.setdefault(uid, set())
        if index is not None:
            return False
        tracks.append(
            {
                "filepath": filepath,
                "title": title,
                "author": author,
                "collection_id": collection_id,
                "added_at": time.time(),
            }
        )
        self._filepath_sets[uid].add(filepath)
        self._save()
        return True

    def remove(
        self,
        user_id: int,
        filepath: str,
    ) -> bool:
        index = self._track_index(user_id, filepath)
        if index is None:
            return False
        tracks = self._data.get(str(user_id), [])
        del tracks[index]
        self._filepath_sets.setdefault(str(user_id), set()).discard(filepath)
        self._save()
        return True

    def get_tracks(self, user_id: int) -> list[dict]:
        self._ensure_loaded()
        return list(self._data.get(str(user_id), []))

    def set_track_metadata(self, user_id: int, filepath: str, title: str, author: str = "") -> bool:
        self._ensure_loaded()
        uid = str(user_id)
        tracks = self._data.get(uid, [])
        for track in tracks:
            if track.get("filepath") == filepath:
                if title:
                    track["title"] = title
                if author:
                    track["author"] = author
                self._save()
                return True
        return False

    def has_track(self, user_id: int, filepath: str) -> bool:
        self._ensure_loaded()
        return filepath in self._filepath_sets.get(str(user_id), set())


class PlaylistLibrary:
    def __init__(self, root_dir: str) -> None:
        self._root_dir = Path(root_dir)
        self._dir = self._root_dir / "var" / "playlists"

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
            "schema_version": PLAYLIST_SCHEMA_VERSION,
            "name": name,
            "author": author_name,
            "author_id": author_id,
            "created": time.time(),
            "tracks": tracks,
        }
        save_json(filepath, data, root_dir=self._root_dir)
        return safe

    def load(self, name: str) -> dict | None:
        safe = self._safe_name(name)
        for ext in ("", ".json"):
            filepath = self._dir / f"{safe}{ext}"
            result = load_json(filepath, root_dir=self._root_dir)
            normalized = _normalize_playlist_record(result)
            if normalized is not None:
                return normalized
        return None

    def list_playlists(self) -> list[dict]:
        playlists: list[dict] = []
        for filepath in sorted(self._dir.glob("*.json")):
            data = load_json(filepath, root_dir=self._root_dir)
            normalized = _normalize_playlist_record(data)
            if not normalized:
                continue
            playlists.append(
                {
                    "name": normalized.get("name", filepath.stem) or filepath.stem,
                    "author": normalized.get("author", "?") or "?",
                    "tracks": len(normalized.get("tracks", [])),
                    "created": normalized.get("created", 0),
                }
            )
        return playlists
