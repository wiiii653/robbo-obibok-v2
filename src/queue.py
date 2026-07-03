"""Queue management — shuffle, blacklist, persistence."""

from __future__ import annotations

import random
from pathlib import Path

from .models import PlaybackState
from .persistence import load_json, save_json


def shuffle_queue(state: PlaybackState) -> None:
    queue = list(state.tracks)
    random.shuffle(queue)
    state.queue = queue
    state.position = 0


def next_track(state: PlaybackState) -> str | None:
    if not state.queue:
        return None
    if state.is_looping:
        return state.queue[state.position]
    state.position += 1
    if state.position >= len(state.queue):
        if not state.is_looping:
            return None
        state.position = 0
    return state.queue[state.position]


def current_track(state: PlaybackState) -> str | None:
    if not state.queue or state.position >= len(state.queue):
        return None
    return state.queue[state.position]


def jump_to(state: PlaybackState, index: int) -> str | None:
    if not state.queue or index < 0 or index >= len(state.queue):
        return None
    state.position = index
    return state.queue[index]


def clear_queue(state: PlaybackState) -> None:
    state.queue = []
    state.position = 0


def save_queue(state: PlaybackState, root_dir: str) -> bool:
    if not state.guild_id:
        return False
    queue_dir = Path(root_dir) / "var" / "queues"
    queue_dir.mkdir(parents=True, exist_ok=True)
    filepath = queue_dir / f"{state.guild_id}.json"
    data = {
        "queue": state.queue,
        "position": state.position,
        "is_looping": state.is_looping,
        "collection_mode": state.collection_mode,
    }
    return save_json(filepath, data)


def load_queue(guild_id: int, root_dir: str) -> dict | None:
    queue_dir = Path(root_dir) / "var" / "queues"
    filepath = queue_dir / f"{guild_id}.json"
    return load_json(filepath)


def restore_queue(data: dict, state: PlaybackState) -> None:
    state.queue = data.get("queue", [])
    state.position = data.get("position", 0)
    state.is_looping = data.get("is_looping", False)
    state.collection_mode = data.get("collection_mode", state.collection_mode)


class Blacklist:
    def __init__(self, root_dir: str) -> None:
        self._filepath = Path(root_dir) / "blacklist.json"
        self._data: dict[str, list[str]] = {}
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

    def is_blacklisted(self, filepath: str) -> bool:
        self._ensure_loaded()
        for tracks in self._data.values():
            if filepath in tracks:
                return True
        return False

    def add(self, user_id: int, filepath: str) -> bool:
        self._ensure_loaded()
        uid = str(user_id)
        tracks = self._data.setdefault(uid, [])
        if filepath in tracks:
            return False
        tracks.append(filepath)
        self._save()
        return True

    def remove(self, user_id: int, filepath: str) -> bool:
        self._ensure_loaded()
        uid = str(user_id)
        tracks = self._data.get(uid, [])
        if filepath not in tracks:
            return False
        tracks.remove(filepath)
        self._save()
        return True

    def remove_by_index(self, user_id: int, index: int) -> str | None:
        self._ensure_loaded()
        uid = str(user_id)
        tracks = self._data.get(uid, [])
        if index < 0 or index >= len(tracks):
            return None
        removed = tracks.pop(index)
        self._save()
        return removed

    def get_tracks(self, user_id: int) -> list[str]:
        self._ensure_loaded()
        return list(self._data.get(str(user_id), []))

    def filter_queue(self, queue: list[str], user_id: int) -> list[str]:
        blocked = set(self.get_tracks(user_id))
        return [t for t in queue if t not in blocked]
