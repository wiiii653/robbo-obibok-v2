"""Queue management — shuffle, blacklist, persistence."""

from __future__ import annotations

from pathlib import Path

from .models import PlaybackState
from .persistence import load_json, save_json

QUEUE_SCHEMA_VERSION = 2
BLACKLIST_SCHEMA_VERSION = 2


def normalize_queue_record(data: object) -> dict | None:
    if not isinstance(data, dict):
        return None
    schema_version = data.get("schema_version", 1)
    if schema_version not in (1, QUEUE_SCHEMA_VERSION):
        return None
    queue = data.get("queue")
    position = data.get("position")
    is_looping = data.get("is_looping")
    collection_mode = data.get("collection_mode")
    queue_collection_ids = data.get("queue_collection_ids")
    if not isinstance(queue, list) or not all(isinstance(item, str) for item in queue):
        return None
    if not isinstance(position, int) or isinstance(position, bool):
        return None
    if queue:
        if position < 0 or position >= len(queue):
            return None
    elif position not in (-1, 0):
        return None
    if not isinstance(is_looping, bool) or not isinstance(collection_mode, str):
        return None
    if queue_collection_ids is None:
        queue_collection_ids = [collection_mode] * len(queue)
    if (
        not isinstance(queue_collection_ids, list)
        or len(queue_collection_ids) != len(queue)
        or not all(isinstance(item, str) and item for item in queue_collection_ids)
    ):
        return None
    return {
        "schema_version": schema_version,
        "queue": list(queue),
        "queue_collection_ids": list(queue_collection_ids),
        "position": position,
        "is_looping": is_looping,
        "collection_mode": collection_mode,
    }


def can_restore_queue(saved: dict | None, tracks: list[str] | None, collection_mode: str) -> bool:
    if not isinstance(saved, dict) or not tracks:
        return False
    if saved.get("collection_mode") != collection_mode:
        return False
    queue = saved.get("queue")
    if not isinstance(queue, list) or not all(isinstance(item, str) for item in queue):
        return False
    # Reject trivially small queues — they are almost certainly remnants
    # from a failed run (e.g. first track failed, queue saved with 1 entry
    # on stop, then restored on next start instead of building a fresh one).
    if len(queue) <= 1:
        return False
    queue_collection_ids = saved.get("queue_collection_ids")
    if queue_collection_ids is not None:
        if (
            not isinstance(queue_collection_ids, list)
            or len(queue_collection_ids) != len(queue)
            or not all(isinstance(item, str) and item for item in queue_collection_ids)
        ):
            return False
    # Set membership — list `in` here is O(n²) and froze the event loop for
    # minutes on large collections (225k-track modarchive queue).
    track_set = set(tracks)
    return all(item in track_set for item in queue)


def next_track(state: PlaybackState) -> str | None:
    if not state.queue:
        return None
    next_position = state.position + 1
    if next_position >= len(state.queue):
        if state.is_looping:
            next_position = 0
        else:
            return None
    state.position = next_position
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
    state.queue_collection_ids = []
    state.position = 0


def save_queue(state: PlaybackState, root_dir: str) -> bool:
    if not state.guild_id:
        return False
    queue_dir = Path(root_dir) / "var" / "queues"
    queue_dir.mkdir(parents=True, exist_ok=True)
    filepath = queue_dir / f"{state.guild_id}.json"
    data = {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "queue": state.queue,
        "queue_collection_ids": state.queue_collection_ids
        if len(state.queue_collection_ids) == len(state.queue)
        else [state.collection_mode] * len(state.queue),
        "position": state.position,
        "is_looping": state.is_looping,
        "collection_mode": state.collection_mode,
    }
    return save_json(filepath, data)


def load_queue(guild_id: int, root_dir: str) -> dict | None:
    queue_dir = Path(root_dir) / "var" / "queues"
    filepath = queue_dir / f"{guild_id}.json"
    return normalize_queue_record(load_json(filepath))


def restore_queue(data: dict, state: PlaybackState) -> None:
    normalized = normalize_queue_record(data)
    if not normalized:
        return
    state.queue = normalized["queue"]
    state.queue_collection_ids = normalized["queue_collection_ids"]
    state.position = normalized["position"]
    state.is_looping = normalized["is_looping"]
    state.collection_mode = normalized["collection_mode"]


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
            normalized: dict[str, list[str]] = {}
            for key, value in raw.items():
                if not isinstance(value, list):
                    continue
                tracks = [track for track in value if isinstance(track, str) and track]
                normalized[key] = tracks
            self._data = normalized
        self._loaded = True

    def _save(self) -> None:
        save_json(self._filepath, {"schema_version": BLACKLIST_SCHEMA_VERSION, **self._data})

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
