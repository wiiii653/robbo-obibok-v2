"""Collection registry, index loaders, and metadata extraction."""

from __future__ import annotations

import re
from pathlib import Path

from .models import COLLECTIONS, FLIP_ORDER, Collection
from .persistence import load_tracks_from_cache

SAP_LINE_RE = re.compile(rb"^([A-Z]+)\s+(.+)")


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


def _clean_metadata(s: str) -> str:
    """Strip leading/f trailing non-printable chars from SID/AY/YM metadata fields."""
    s = s.strip("\x00 ")
    # Strip leading control characters (ASCII < 32)
    while s and ord(s[0]) < 32:
        s = s[1:]
    return s


def parse_sid_header(filepath: str) -> dict[str, str]:
    try:
        with open(filepath, "rb") as f:
            data = f.read(256)
    except OSError:
        return {}
    if len(data) < 256 or data[:4] != b"PSID":
        return {}
    title = data[16:48].decode("ascii", errors="replace")
    author = data[48:80].decode("ascii", errors="replace")
    copyright = data[80:112].decode("ascii", errors="replace")
    return {
        "NAME": _clean_metadata(title),
        "AUTHOR": _clean_metadata(author),
        "COPYRIGHT": _clean_metadata(copyright),
    }


def parse_mod_header(filepath: str) -> dict[str, str]:
    try:
        with open(filepath, "rb") as f:
            data = f.read(1084)
    except OSError:
        return {}
    title = data[:20].decode("ascii", errors="replace").strip("\x00")
    return {"NAME": title}


def parse_xm_header(filepath: str) -> dict[str, str]:
    return _parse_title(filepath, offset=17, length=20)


def parse_s3m_header(filepath: str) -> dict[str, str]:
    return _parse_title(filepath, offset=0, length=28)


def parse_it_header(filepath: str) -> dict[str, str]:
    return _parse_title(filepath, offset=4, length=26)


def _parse_title(filepath: str, *, offset: int, length: int) -> dict[str, str]:
    try:
        with open(filepath, "rb") as f:
            f.seek(offset)
            data = f.read(length)
    except OSError:
        return {}
    title = data.decode("ascii", errors="replace").rstrip("\x00 ")
    return {"NAME": _clean_metadata(title)}


def resolve_collection_for_filepath(filepath: str) -> str | None:
    """Determine which collection a filepath belongs to (based on extension/URL patterns).

    Like v1's favplay logic: check extension and URL patterns to resolve the collection
    dynamically instead of relying on saved state.
    """
    from .remote import is_remote_track
    if is_remote_track(filepath):
        low = filepath.lower()
        # ModArchive URLs
        if "modarchive" in low or "moduleid=" in low:
            return "modarchive"
        # HVSC URLs
        if "hvsc" in low or "c64" in low or filepath.endswith(".sid"):
            return "hvsc"
        # ASMA URLs
        if "asma" in low or "atari" in low or filepath.endswith(".sap"):
            return "asma"
        return None

    # Local track — check extension against each collection
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    if not ext:
        return None

    # Unambiguous extensions
    extension_map = {
        "sid": "hvsc",
        "sap": "asma",
        "ay": "ay",
        "ym": "ym",
    }
    if ext in extension_map:
        return extension_map[ext]

    # Ambiguous module extensions — check each collection's extension list
    # Priority: more specific collections first, fallback to modarchive
    for col_id in ("tiny", "kgen", "modarchive"):
        col = COLLECTIONS.get(col_id)
        if col and ext in col.extensions:
            return col_id

    return None


def extract_metadata(filepath: str, collection_id: str) -> dict[str, str]:
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    if ext == "sap":
        return parse_sap_header(filepath)
    if ext == "sid":
        return parse_sid_header(filepath)
    if ext == "mod":
        return parse_mod_header(filepath)
    if ext == "xm":
        return parse_xm_header(filepath)
    if ext == "s3m":
        return parse_s3m_header(filepath)
    if ext == "it":
        return parse_it_header(filepath)
    return {}
