"""Playback orchestrator — ties together audio, queue, collections, monitor."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .audio import AudioController
from .collection_loader import extract_metadata, get_collection, load_raw_paths
from .favorites import Favorites
from .models import PlaybackState
from .queue import Blacklist, clear_queue, current_track, jump_to, next_track

logger = logging.getLogger(__name__)


@dataclass
class PlaybackEngine:
    audio: AudioController
    favorites: Favorites
    blacklist: Blacklist
    root_dir: str

    def start_radio(self, state: PlaybackState, collection_id: str | None = None, user_id: int = 0) -> str | None:
        if collection_id:
            state.collection_mode = collection_id
        paths = load_raw_paths(state.collection_mode, self.root_dir)
        if not paths:
            return None
        state.tracks = paths
        blacklist_tracks = self.blacklist.get_tracks(user_id)
        filtered = [p for p in paths if p not in blacklist_tracks]
        state.queue = filtered
        import random
        random.shuffle(state.queue)
        state.position = 0
        track = current_track(state)
        if track:
            self.audio.set_collection_volume(state.collection_mode)
        return track

    async def play_track(self, state: PlaybackState) -> str | None:
        track = current_track(state)
        if not track:
            return None
        col = get_collection(state.collection_mode)
        if not col:
            return None
        full_path = f"{self.root_dir}/{col.archive_path}/{track}"
        success = await asyncio.to_thread(self.audio.play, full_path)
        if success:
            state.current_track = track
            state.is_playing = True
            state.played_count += 1
            state.history.append(track)
            if len(state.history) > 20:
                state.history = state.history[-20:]
        return track if success else None

    async def skip_track(self, state: PlaybackState) -> str | None:
        track = next_track(state)
        if not track:
            return None
        return await self.play_track(state)

    async def stop(self, state: PlaybackState) -> None:
        await asyncio.to_thread(self.audio.stop)
        state.is_playing = False

    async def jump_to_track(self, state: PlaybackState, index: int) -> str | None:
        track = jump_to(state, index)
        if not track:
            return None
        return await self.play_track(state)

    def toggle_loop(self, state: PlaybackState) -> bool:
        state.is_looping = not state.is_looping
        return state.is_looping

    async def clear(self, state: PlaybackState) -> None:
        clear_queue(state)
        await asyncio.to_thread(self.audio.stop)
        state.is_playing = False

    def search(self, query: str, state: PlaybackState) -> list[str]:
        query_lower = query.lower()
        results: list[str] = []
        for path in state.tracks:
            filename = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ")
            if query_lower in filename.lower():
                results.append(path)
                if len(results) >= 10:
                    break
        return results

    def get_track_metadata(self, filepath: str, collection_id: str) -> dict[str, str]:
        col = get_collection(collection_id)
        if not col:
            return {}
        full_path = f"{self.root_dir}/{col.archive_path}/{filepath}"
        return extract_metadata(full_path, collection_id)

    def toggle_favorite(self, user_id: int, filepath: str, collection_id: str) -> bool:
        meta = self.get_track_metadata(filepath, collection_id)
        title = meta.get("NAME", filepath.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        return self.favorites.toggle(user_id, filepath, title, collection_id)

    def blacklist_current(self, user_id: int, state: PlaybackState) -> bool:
        track = current_track(state)
        if not track:
            return False
        return self.blacklist.add(user_id, track)

    def queue_info(self, state: PlaybackState) -> list[dict]:
        info: list[dict] = []
        for i, path in enumerate(state.queue):
            filename = path.rsplit("/", 1)[-1]
            info.append({
                "index": i,
                "path": path,
                "filename": filename,
                "is_current": i == state.position,
            })
        return info
