"""Playback orchestrator — ties together audio, queue, collections, monitor."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from .audio import AudioController
from .collection_loader import extract_metadata, get_collection, load_raw_paths
from .favorites import Favorites
from .models import PlaybackState
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
from .remote import (
    download_modarchive_module,
    download_remote_track,
    download_youtube_track,
    is_remote_track,
    is_youtube_url,
    remote_cache_path,
    uses_module_cache,
)
from .subsong import cleanup_subsong_files, convert_subsong, get_subsongs, subsong_temp_path

logger = logging.getLogger(__name__)


@dataclass
class PlaybackEngine:
    audio: AudioController
    favorites: Favorites
    blacklist: Blacklist
    root_dir: str
    archive_root: str = "archiwum"
    shuffle_queue: bool = True

    def _clear_subsong_state(self, state: PlaybackState) -> None:
        cleanup_subsong_files(state.subsong_wavs)
        state.subsong_wavs = []
        state.subsong_path = ""
        state.subsong_current = -1
        state.subsong_total = 0

    def _clear_remote_state(self, state: PlaybackState) -> None:
        state.predownload_path = ""
        state.predownload_url = ""

    def _prepare_subsong_playback(self, state: PlaybackState, track_path: Path) -> Path:
        track_key = str(track_path)
        ext = track_key.rsplit(".", 1)[-1].lower() if "." in track_key else ""
        # AY/YM and all module formats are handled natively by Audacious
        # (console.so for SID/SAP/AY/YM, built-in player for MOD/XM/S3M/IT/DMF/MED)
        # Skip ffmpeg conversion and subsong detection for all of them
        MODULE_EXTENSIONS = {"mod", "xm", "s3m", "it", "dmf", "med", "sid", "sap"}
        if ext in ("ay", "ym") or ext in MODULE_EXTENSIONS:
            return track_path
        if state.subsong_path != track_key:
            self._clear_subsong_state(state)
            state.subsong_path = track_key
            durations = get_subsongs(track_key)
            state.subsong_total = len(durations)
            state.subsong_current = 0 if state.subsong_total > 1 else -1
        if state.subsong_total > 1 and state.subsong_current >= 0:
            wav_path = subsong_temp_path(self.root_dir, track_key, state.subsong_current)
            if wav_path not in state.subsong_wavs:
                if convert_subsong(track_key, state.subsong_current, wav_path):
                    state.subsong_wavs.append(wav_path)
            return Path(wav_path) if Path(wav_path).exists() else track_path
        return track_path

    async def start_radio(self, state: PlaybackState, collection_id: str | None = None, user_id: int = 0) -> str | None:
        if collection_id:
            state.collection_mode = collection_id
        paths = load_raw_paths(state.collection_mode, self.root_dir)
        if not paths:
            return None
        state.tracks = paths
        self._clear_subsong_state(state)
        self._clear_remote_state(state)
        blacklist_tracks = self.blacklist.get_tracks(user_id)
        filtered = [p for p in paths if p not in blacklist_tracks]
        restored = False
        if state.guild_id:
            saved = load_queue(state.guild_id, self.root_dir)
            if can_restore_queue(saved, filtered, state.collection_mode):
                restore_queue(saved, state)
                restored = True
        if not restored:
            import random

            state.queue = filtered
            if self.shuffle_queue:
                random.shuffle(state.queue)
            state.queue_collection_ids = [state.collection_mode] * len(state.queue)
            state.position = 0
        track = current_track(state)
        if track:
            if state.guild_id:
                save_queue(state, self.root_dir)
        return track

    async def play_track(self, state: PlaybackState) -> str | None:
        for _attempt in range(5):  # skip up to 5 bad tracks
            track = current_track(state)
            if not track:
                return None
            playback_path = await self._resolve_track_path(state, track)
            if playback_path is None:
                logger.warning("play_track: track not resolved, skipping: %s", track)
                if next_track(state) is None:
                    return None
                continue
            playback_path = self._prepare_subsong_playback(state, playback_path)
            await self.audio.async_set_volume_for_playback(str(playback_path))
            success = await asyncio.to_thread(self.audio.play, str(playback_path))
            if success:
                state.current_track = track
                state.current_collection_id = self._collection_for_position(state)
                state.is_playing = True
                state.played_count += 1
                state.history.append(track)
                if len(state.history) > 20:
                    state.history = state.history[-20:]
                save_queue(state, self.root_dir)
                self._clear_remote_state(state)
                return track
            # Play failed — skip to next track instead of stopping the radio
            logger.warning("play_track: failed to play %s, skipping to next", track)
            if next_track(state) is None:
                return None
        logger.error("play_track: exhausted 5 skips, giving up")
        return None

    async def skip_track(self, state: PlaybackState) -> str | None:
        if state.subsong_total > 1 and state.subsong_path:
            if state.subsong_current + 1 < state.subsong_total:
                state.subsong_current += 1
                return await self.play_track(state)
            self._clear_subsong_state(state)
        track = next_track(state)
        if not track:
            return None
        return await self.play_track(state)

    async def stop(self, state: PlaybackState) -> None:
        self.audio.stop()
        state.is_playing = False
        state.current_track = ""
        state.current_collection_id = ""
        self._clear_subsong_state(state)
        self._clear_remote_state(state)
        save_queue(state, self.root_dir)

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
        self.audio.stop()
        state.is_playing = False
        state.current_track = ""
        state.current_collection_id = ""
        self._clear_subsong_state(state)
        self._clear_remote_state(state)
        save_queue(state, self.root_dir)

    def search(self, query: str, state: PlaybackState) -> list[str]:
        query_lower = query.lower()
        results: list[str] = []
        col = get_collection(state.collection_mode)
        for path in state.tracks:
            normalized_path = path.replace("\\", "/")
            filename = normalized_path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ")
            directory = normalized_path.rsplit("/", 1)[0].replace("_", " ") if "/" in normalized_path else ""
            if query_lower in filename.lower() or query_lower in normalized_path.lower() or (
                directory and query_lower in directory.lower()
            ):
                results.append(path)
                if len(results) >= 10:
                    break
                continue

            if not col:
                continue
            full_path = Path(self.root_dir) / self.archive_root / col.archive_path / path
            meta = extract_metadata(str(full_path), state.collection_mode)
            name = meta.get("NAME", meta.get("name", ""))
            author = meta.get("AUTHOR", meta.get("author", ""))
            if query_lower in name.lower() or query_lower in author.lower():
                results.append(path)
                if len(results) >= 10:
                    break
        return results

    async def predownload_next(self, state: PlaybackState) -> str | None:
        if not state.queue:
            return None
        next_index = state.position + 1
        if next_index >= len(state.queue):
            if state.is_looping:
                next_index = 0
            else:
                return None
        next_track = state.queue[next_index]
        if not is_remote_track(next_track):
            return None
        if state.predownload_url == next_track and state.predownload_path and Path(state.predownload_path).exists():
            return state.predownload_path
        try:
            output_path = await self._download_remote_track(state, next_track)
        except Exception as exc:
            logger.warning("Remote predownload failed for %s: %s", next_track, exc)
            return None
        if output_path:
            state.predownload_url = next_track
            state.predownload_path = output_path
        return output_path

    def describe_search_result(self, filepath: str, collection_id: str, index: int | None = None) -> str:
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
        if is_remote_track(filepath):
            from urllib.parse import unquote, urlparse
            parsed = urlparse(filepath)
            # For ModArchive URLs, use module ID as label
            if "moduleid=" in filepath:
                mod_id = filepath.split("moduleid=", 1)[-1].split("&", 1)[0]
                return {"NAME": f"ModArchive #{mod_id}", "AUTHOR": ""}
            # For other remote tracks, extract a readable name from the URL path
            stem = Path(unquote(parsed.path)).stem or "remote"
            clean = stem.replace("_", " ").replace("-", " ").strip()
            return {"NAME": clean.title() if clean else "Remote Track", "AUTHOR": ""}
        col = get_collection(collection_id)
        if not col:
            return {}
        full_path = Path(self.root_dir) / self.archive_root / col.archive_path / filepath
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
            info.append({
                "index": i,
                "path": path,
                "filename": filename,
                "is_current": i == state.position,
            })
        return info

    async def _resolve_track_path(self, state: PlaybackState, track: str) -> Path | None:
        if is_remote_track(track):
            if state.predownload_url == track and state.predownload_path:
                cached_path = Path(state.predownload_path)
                if cached_path.exists():
                    return cached_path
            try:
                output_path = await self._download_remote_track(state, track)
            except Exception as exc:
                logger.warning("Remote download failed for %s: %s", track, exc)
                return None
            if output_path:
                state.predownload_url = track
                state.predownload_path = output_path
                return Path(output_path)
            return None

        col = get_collection(self._collection_for_position(state))
        if not col:
            return None
        return Path(self.root_dir) / self.archive_root / col.archive_path / track

    async def _download_remote_track(self, state: PlaybackState, track: str) -> str | None:
        if is_youtube_url(track):
            return await asyncio.to_thread(download_youtube_track, track, self.root_dir)
        if uses_module_cache(track):
            return download_modarchive_module(track, root_dir=self.root_dir)
        output_path = remote_cache_path(self.root_dir, track)
        return download_remote_track(track, output_path)
