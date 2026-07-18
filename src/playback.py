"""Playback orchestrator — ties together audio, queue, collections, monitor."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .audio import AudioController
from .collection_loader import extract_metadata, get_collection, load_raw_paths
from .favorites import Favorites
from .models import Collection, PlaybackState
from .queue import (
    Blacklist,
    can_restore_queue,
    clear_queue,
    current_track,
    jump_to,
    load_queue,
    next_track,
    restore_queue,
    save_queue,
)

logger = logging.getLogger(__name__)

# Max file metadata reads per search. Path matching is cheap string work,
# but the metadata fallback opens one file per track — unbounded, that meant
# thousands of file opens on modarchive-sized (225k) collections.
MAX_METADATA_PROBES = 500

# Min seconds between per-track queue writes. A full queue file can be
# 10MB+ (modarchive) — rewriting it on every track change is wasteful.
# stop/clear still save immediately; a crash just resumes a few tracks back.
QUEUE_SAVE_MIN_INTERVAL = 60.0


@dataclass
class PlaybackEngine:
    audio: AudioController
    favorites: Favorites
    blacklist: Blacklist
    root_dir: str
    archive_root: str = "archiwum"
    shuffle_queue: bool = True
    default_loop: bool = False
    _guild_locks: dict[int, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)
    _last_queue_save: dict[int, float] = field(default_factory=dict, init=False, repr=False)

    async def _save_queue(self, state: PlaybackState, *, immediate: bool = False) -> None:
        """Persist the queue; per-track saves are debounced per guild."""
        if not state.guild_id:
            return
        now = time.monotonic()
        if (
            not immediate
            and now - self._last_queue_save.get(state.guild_id, 0.0) < QUEUE_SAVE_MIN_INTERVAL
        ):
            return
        self._last_queue_save[state.guild_id] = now
        await asyncio.to_thread(save_queue, state, self.root_dir)

    def _lock_for(self, state: PlaybackState) -> asyncio.Lock:
        return self._guild_locks.setdefault(state.guild_id, asyncio.Lock())

    def _reset_runtime_state(self, state: PlaybackState) -> None:
        state.current_track = ""
        state.current_collection_id = ""
        state.is_playing = False
        state.voice_channel_id = None
        state.queue_owner_user_id = 0
        state.search_results = []
        state.search_collection_id = ""

    async def start_radio(
        self, state: PlaybackState, collection_id: str | None = None, user_id: int = 0
    ) -> str | None:
        if collection_id:
            state.collection_mode = collection_id
        paths = await asyncio.to_thread(load_raw_paths, state.collection_mode, self.root_dir)
        if not paths:
            return None
        state.tracks = paths
        self._reset_runtime_state(state)
        state.queue_owner_user_id = user_id
        blacklist_tracks = set(await asyncio.to_thread(self.blacklist.get_tracks, user_id))
        filtered = [p for p in paths if p not in blacklist_tracks]
        restored = False
        if state.guild_id:
            saved = await asyncio.to_thread(load_queue, state.guild_id, self.root_dir)
            if can_restore_queue(saved, filtered, state.collection_mode):
                restore_queue(saved, state)
                state.is_looping = self.default_loop  # <-- config overrides saved value
                restored = True
        if not restored:
            import random

            state.queue = filtered
            if self.shuffle_queue:
                random.shuffle(state.queue)
            state.queue_collection_ids = [state.collection_mode] * len(state.queue)
            state.position = 0
            state.is_looping = self.default_loop
        track = current_track(state)
        if track:
            await self._save_queue(state, immediate=True)
        return track

    async def play_track(self, state: PlaybackState) -> str | None:
        async with self._lock_for(state):
            return await self._play_track_unlocked(state)

    async def _play_track_unlocked(self, state: PlaybackState) -> str | None:
        consecutive_fails = 0
        start_pos = state.position
        while True:
            track = current_track(state)
            if not track:
                return None
            # Circuit-breaker: if we've looped back to the start position after
            # advancing through the whole queue, every track is bad — give up.
            if consecutive_fails > 0 and state.position == start_pos:
                logger.error(
                    "All %d tracks failed — giving up after %d consecutive failures",
                    len(state.queue),
                    consecutive_fails,
                )
                state.is_playing = False
                state.current_track = ""
                state.current_collection_id = ""
                return None
            consecutive_fails += 1

            playback_path = await self._resolve_track_path(state, track)
            if playback_path is None or not playback_path.exists():
                logger.warning("play_track: track not resolved, skipping: %s", track)
                state.skipped_tracks += 1
                if next_track(state) is None:
                    state.is_playing = False
                    state.current_track = ""
                    state.current_collection_id = ""
                    return None
                continue
            await asyncio.to_thread(self.audio.set_volume_for_playback, str(playback_path))
            success = await asyncio.to_thread(self.audio.play, str(playback_path))
            if success:
                state.current_track = track
                state.current_collection_id = self._collection_for_position(state)
                state.is_playing = True
                state.played_count += 1
                state.skipped_tracks = 0  # reset on successful play
                state.history.append(track)
                if len(state.history) > 20:
                    state.history = state.history[-20:]
                await self._save_queue(state)
                return track
            # Play failed — skip to next track instead of stopping the radio
            logger.warning("play_track: failed to play %s, skipping to next", track)
            state.skipped_tracks += 1
            if next_track(state) is None:
                state.is_playing = False
                state.current_track = ""
                state.current_collection_id = ""
                return None

    async def skip_track(self, state: PlaybackState) -> str | None:
        async with self._lock_for(state):
            track = next_track(state)
            if not track:
                return None
            return await self._play_track_unlocked(state)

    async def stop(self, state: PlaybackState) -> None:
        async with self._lock_for(state):
            await asyncio.to_thread(self.audio.stop)
            self._reset_runtime_state(state)
            await self._save_queue(state, immediate=True)

    async def jump_to_track(self, state: PlaybackState, index: int) -> str | None:
        async with self._lock_for(state):
            track = jump_to(state, index)
            if not track:
                return None
            return await self._play_track_unlocked(state)

    def toggle_loop(self, state: PlaybackState) -> bool:
        state.is_looping = not state.is_looping
        return state.is_looping

    async def clear(self, state: PlaybackState) -> None:
        async with self._lock_for(state):
            clear_queue(state)
            await asyncio.to_thread(self.audio.stop)
            self._reset_runtime_state(state)
            await self._save_queue(state, immediate=True)

    def _build_track_path(self, col: Collection, track: str) -> Path:
        """Build the full filesystem path for a track, handling archive_path prefix dedup."""
        archive_parts = col.archive_path.split("/")
        if len(archive_parts) > 1 and track.replace("\\", "/").startswith(archive_parts[-1] + "/"):
            base = "/".join(archive_parts[:-1])
            return Path(self.root_dir) / self.archive_root / base / track
        return Path(self.root_dir) / self.archive_root / col.archive_path / track

    def search(self, query: str, state: PlaybackState) -> list[str]:
        query_lower = query.lower()
        results: list[str] = []
        col = get_collection(state.collection_mode)
        metadata_probes = 0
        probe_cap_logged = False
        for path in state.tracks:
            normalized_path = path.replace("\\", "/")
            filename = normalized_path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ")
            directory = (
                normalized_path.rsplit("/", 1)[0].replace("_", " ")
                if "/" in normalized_path
                else ""
            )
            if (
                query_lower in filename.lower()
                or query_lower in normalized_path.lower()
                or (directory and query_lower in directory.lower())
            ):
                results.append(path)
                if len(results) >= 10:
                    break
                continue

            if not col:
                continue
            if metadata_probes >= MAX_METADATA_PROBES:
                if not probe_cap_logged:
                    logger.info(
                        "search: metadata probe cap (%d) reached for query %r; "
                        "continuing with path-only matching",
                        MAX_METADATA_PROBES,
                        query,
                    )
                    probe_cap_logged = True
                continue
            metadata_probes += 1
            full_path = self._build_track_path(col, path)
            meta = extract_metadata(str(full_path), state.collection_mode)
            name = meta.get("NAME", meta.get("name", ""))
            author = meta.get("AUTHOR", meta.get("author", ""))
            if query_lower in name.lower() or query_lower in author.lower():
                results.append(path)
                if len(results) >= 10:
                    break
        return results

    def describe_search_result(
        self, filepath: str, collection_id: str, index: int | None = None
    ) -> str:
        col = get_collection(collection_id)
        meta = self.get_track_metadata(filepath, collection_id)
        normalized = filepath.replace("\\", "/")
        filename = normalized.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ")
        title = meta.get("NAME", meta.get("name", filename)) or filename
        author = meta.get("AUTHOR", meta.get("author", "")) or ""
        directory = normalized.rsplit("/", 1)[0].replace("_", " ") if "/" in normalized else ""
        prefix = f"`{index}.` " if index is not None else ""
        if col and col.id == "modarchive":
            parts = [prefix + title]
            if author:
                parts.append(f"by {author}")
            return " ".join(parts)
        if col and col.id == "asma" and directory:
            label = f"{title} ({directory.split('/')[-1]})"
        elif directory and directory != title:
            label = f"{title} ({directory.split('/')[-1]})"
        else:
            label = title
        if author:
            label = f"{label} — {author}"
        return prefix + label

    def get_track_metadata(self, filepath: str, collection_id: str) -> dict[str, str]:
        col = get_collection(collection_id)
        if not col:
            return {}
        full_path = self._build_track_path(col, filepath)
        return extract_metadata(str(full_path), collection_id)

    def _collection_for_position(self, state: PlaybackState) -> str:
        if 0 <= state.position < len(state.queue_collection_ids):
            return state.queue_collection_ids[state.position]
        return state.collection_mode

    def toggle_favorite(self, user_id: int, filepath: str, collection_id: str) -> bool:
        meta = self.get_track_metadata(filepath, collection_id)
        title = meta.get("NAME", filepath.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        author = meta.get("AUTHOR", "")
        return self.favorites.toggle(user_id, filepath, title, collection_id, author)

    def blacklist_current(self, user_id: int, state: PlaybackState) -> bool:
        track = current_track(state)
        if not track:
            return False
        return self.blacklist.add(user_id, track)

    def queue_info(self, state: PlaybackState) -> list[dict]:
        info: list[dict] = []
        for i, path in enumerate(state.queue):
            filename = path.rsplit("/", 1)[-1]
            info.append(
                {
                    "index": i,
                    "path": path,
                    "filename": filename,
                    "is_current": i == state.position,
                }
            )
        return info

    async def _resolve_track_path(self, state: PlaybackState, track: str) -> Path | None:
        col = get_collection(self._collection_for_position(state))
        if not col:
            return None
        return self._build_track_path(col, track)
