"""Songlengths.md5 lookup — ground-truth SID durations for timeout computation.

The sidplayfp Audacious plugin hard-caps SIDs it cannot resolve in *its*
database copy at ``playMaxTime`` (an audible cut). Files outside HVSC
frequently miss there, so the bot resolves durations itself from
Songlengths.md5 and feeds the real length into the monitor's wall-clock
timeouts (see :mod:`src.monitor`).

Database format (HVSC ``DOCUMENTS/Songlengths.md5``)::

    [Database]
    ; /DEMOS/0-9/10_Orbyte.sid
    5f08a730b280e54fd1e75a7046b93fdc=1:17

Keys are MD5 hex digests over the raw SID file bytes. Values are colon-based
durations, space-separated per subsong (``0:12.97 0:02.898``).

The bot additionally keeps a small *learned* database
(``var/songlengths_custom.md5``, same format) for SIDs missing from every
official source — the monitor records their natural end there, and it is
consulted LAST so its freshest measurement wins.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

SYSTEM_DB_PATH = "/usr/share/sidplayfp/Songlengths.md5"
ARCHIVE_DB_SUBPATH = "hvsc/C64Music/DOCUMENTS/Songlengths.md5"
# Learned lengths for SIDs missing from every official database (party/,
# legacy/, kgen/ drops). Loaded last, so its entries win lookups.
CUSTOM_DB_NAME = "songlengths_custom.md5"

_lock = threading.Lock()
_custom_lock = threading.Lock()
_db_text: str | None = None
_loaded_path: str = ""


def parse_songlength_value(value: str) -> int:
    """Return total seconds for a Songlengths value, summing all subsongs.

    ``'2:54'`` -> 174; ``'1:03.83'`` -> 64 (ceiling); ``'0:12.97 0:02.898'``
    -> 16.  Malformed fragments are skipped; garbage yields 0.
    """
    total = 0.0
    seen_fragment = False
    for fragment in value.split():
        parts = fragment.split(":")
        try:
            if len(parts) == 2:
                total += int(parts[0]) * 60 + float(parts[1])
                seen_fragment = True
            elif len(parts) == 3:
                total += int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                seen_fragment = True
        except ValueError:
            continue
    if not seen_fragment or total <= 0:
        return 0
    return math.ceil(total)


def _default_root_dir() -> str:
    """Repo root (parent of src/) — home of ``var/songlengths_custom.md5``."""
    return str(Path(__file__).resolve().parent.parent)


def custom_db_path(root_dir: str | None = None) -> str:
    """Path of the append-only learned-lengths database."""
    base = Path(root_dir) if root_dir else Path(_default_root_dir())
    return str(base / "var" / CUSTOM_DB_NAME)


def candidate_db_paths(
    archive_root: str | None = None, *, root_dir: str | None = None
) -> list[str]:
    """Ordered candidates: env override, system, archive, learned custom.

    An explicit ``ROBBO_SONGLENGTHS_DB`` override replaces the official
    sources (system + archive), but the learned custom database is always
    appended last so freshest measurements keep winning.
    """
    paths: list[str] = []
    override = os.environ.get("ROBBO_SONGLENGTHS_DB")
    if override:
        paths.append(override)
    else:
        paths.append(SYSTEM_DB_PATH)
        if archive_root:
            paths.append(str(Path(archive_root) / ARCHIVE_DB_SUBPATH))
    paths.append(custom_db_path(root_dir))
    return paths


def _load_db() -> str:
    """Load and cache the first available Songlengths.md5 (thread-safe)."""
    global _db_text, _loaded_path
    if _db_text is not None:
        return _db_text
    with _lock:
        if _db_text is not None:
            return _db_text
        archive_root: str | None = None
        try:  # optional coupling: reuse the configured archive root if present
            from .config import load_config

            archive_root = load_config().archive_path
        except Exception:
            archive_root = None
        parts: list[str] = []
        used: list[str] = []
        for path in candidate_db_paths(archive_root):
            try:
                text = Path(path).read_text(errors="replace")
            except OSError:
                continue
            parts.append(text)
            used.append(path)
            logger.info(
                "Loaded SID song-length database (%d entries) from %s",
                text.count("="),
                path,
            )
        if parts:
            # Later sources win lookups: the finder in lookup_sid_total_time
            # returns the LAST match, so the learned custom db (appended
            # last) overrides stale system/archive entries for one MD5.
            _db_text = "".join(p if p.endswith("\n") else p + "\n" for p in parts)
            _loaded_path = ",".join(used)
            logger.info("SID song-length sources merged: %d", len(used))
            return _db_text
    logger.warning("No Songlengths.md5 database found; SID length lookups disabled")
    _db_text = ""
    return _db_text


def loaded_db_path() -> str:
    """Return the path of the cached database ('' if not loaded yet)."""
    return _loaded_path


def reset_cache() -> None:
    """Drop the cached database (test hook)."""
    global _db_text, _loaded_path
    with _lock:
        _db_text = None
        _loaded_path = ""


def lookup_sid_total_time(filepath: str, *, db_path: str | None = None) -> int | None:
    """Return the known total playback seconds for a SID file, or None.

    Multi-subsong values are summed (the player may cycle every subtune);
    the monitor's not-playing grace catches earlier genuine stops, so an
    over-long timeout only delays the next track — it never cuts audio.
    """
    lower = filepath.lower()
    if not lower.endswith((".sid", ".psid", ".rsid")):
        return None
    try:
        digest = hashlib.md5(
            Path(filepath).read_bytes(), usedforsecurity=False
        ).hexdigest()
    except OSError:
        return None
    text = Path(db_path).read_text(errors="replace") if db_path else _load_db()
    if not text:
        return None
    idx = text.rfind(f"\n{digest}=")
    if idx == -1:
        return None
    start = idx + 1 + len(digest) + 1  # skip "\n", digest and "="
    line_end = text.find("\n", start)
    value = text[start : line_end if line_end != -1 else len(text)].strip()
    seconds = parse_songlength_value(value)
    return seconds or None


def record_sid_length(filepath: str, seconds: int) -> bool:
    """Persist a measured SID duration into the learned custom database.

    Accepts only plausible durations (``0 < s <= 36000`` — the monitor's
    sanity bound). Entries use the standard ``md5=m:ss`` format; a repeated
    measurement for the same digest replaces the older one. Returns True
    when the database was written; the in-memory cache (if already loaded)
    sees the new entry immediately, without a restart.
    """
    lower = filepath.lower()
    if not lower.endswith((".sid", ".psid", ".rsid")):
        return False
    if seconds <= 0 or seconds > 36000:
        return False
    global _db_text
    try:
        digest = hashlib.md5(
            Path(filepath).read_bytes(), usedforsecurity=False
        ).hexdigest()
    except OSError:
        return False
    value = f"{seconds // 60}:{seconds % 60:02d}"
    path = Path(custom_db_path())
    with _custom_lock:
        entries: dict[str, str] = {}
        try:
            if path.exists():
                for line in path.read_text(errors="replace").splitlines():
                    key, sep, val = line.partition("=")
                    key = key.strip().lower()
                    if (
                        sep
                        and len(key) == 32
                        and all(c in "0123456789abcdef" for c in key)
                    ):
                        entries[key] = val.strip()
            entries[digest] = value
            body = "[Database]\n" + "".join(f"{k}={v}\n" for k, v in entries.items())
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / (path.name + ".tmp")
            tmp.write_text(body)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("Could not write %s: %s", path, exc)
            return False
    # Make the new entry visible to already-loaded cached lookups; replace
    # any previous line for this digest so re-measurements stay clean.
    with _lock:
        if _db_text:
            kept = [ln for ln in _db_text.splitlines() if not ln.startswith(f"{digest}=")]
            kept.append(f"{digest}={value}")
            _db_text = "\n".join(kept) + "\n"
    logger.debug("Recorded %s=%s in %s", digest, value, path)
    return True
