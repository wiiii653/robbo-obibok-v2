"""Collection registry, index loaders, and metadata extraction."""

from __future__ import annotations

import re
from pathlib import Path

from .models import COLLECTIONS, FLIP_ORDER, Collection, Track
from .persistence import load_tracks_from_cache

SAP_LINE_RE = re.compile(rb"^([A-Z]+)\s+(.+)")


def load_index(collection_id: str, root_dir: str = ".") -> list[Track] | None:
    col = COLLECTIONS.get(collection_id)
    if not col:
        return None
    cache_path = Path(root_dir) / col.cache_file
    paths = load_tracks_from_cache(cache_path)
    if not paths:
        return None
    return [Track.from_cache_entry({"path": p}, collection_id) for p in paths]


def load_raw_paths(collection_id: str, root_dir: str = ".") -> list[str] | None:
    col = COLLECTIONS.get(collection_id)
    if not col:
        return None
    cache_path = Path(root_dir) / col.cache_file
    return load_tracks_from_cache(cache_path)


def flip_collection(current_id: str) -> str:
    try:
        idx = FLIP_ORDER.index(current_id)
    except ValueError:
        return FLIP_ORDER[0]
    return FLIP_ORDER[(idx + 1) % len(FLIP_ORDER)]


def get_collection(collection_id: str) -> Collection | None:
    return COLLECTIONS.get(collection_id)


def search_tracks(query: str, tracks: list[Track], limit: int = 10) -> list[Track]:
    query_lower = query.lower()
    results: list[Track] = []
    for track in tracks:
        searchable = f"{track.title} {track.author} {track.filepath}".lower()
        if query_lower in searchable:
            results.append(track)
            if len(results) >= limit:
                break
    return results


def parse_sap_header(filepath: str) -> dict[str, str]:
    try:
        with open(filepath, "rb") as f:
            data = f.read(4096)
    except OSError:
        return {}
    meta: dict[str, str] = {}
    for raw_line in data.split(b"\n"):
        line = raw_line.strip()
        if not line or line == b"SAP":
            continue
        if line.startswith(b";"):
            line = line[1:].strip()
        match = SAP_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1).decode("ascii", errors="replace").strip().upper()
        val = match.group(2).decode("ascii", errors="replace").strip()
        meta[key] = val.strip("\"'")
    return meta


def parse_sid_header(filepath: str) -> dict[str, str]:
    try:
        with open(filepath, "rb") as f:
            data = f.read(256)
    except OSError:
        return {}
    if len(data) < 256 or data[:4] != b"PSID":
        return {}
    title = data[16:48].decode("ascii", errors="replace").strip("\x00")
    author = data[48:80].decode("ascii", errors="replace").strip("\x00")
    copyright = data[80:112].decode("ascii", errors="replace").strip("\x00")
    return {"NAME": title, "AUTHOR": author, "COPYRIGHT": copyright}


def parse_mod_header(filepath: str) -> dict[str, str]:
    try:
        with open(filepath, "rb") as f:
            data = f.read(1084)
    except OSError:
        return {}
    title = data[:20].decode("ascii", errors="replace").strip("\x00")
    return {"NAME": title}


def extract_metadata(filepath: str, collection_id: str) -> dict[str, str]:
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    if ext == "sap":
        return parse_sap_header(filepath)
    if ext == "sid":
        return parse_sid_header(filepath)
    if ext in ("mod", "xm", "s3m", "it"):
        return parse_mod_header(filepath)
    return {}


def ensure_archives(root_dir: str = ".") -> None:
    root = Path(root_dir)
    for col in COLLECTIONS.values():
        archive_dir = root / col.archive_path
        archive_dir.mkdir(parents=True, exist_ok=True)
