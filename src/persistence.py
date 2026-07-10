"""JSON file I/O for persistence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - production deployments are Linux
    fcntl = None


logger = logging.getLogger(__name__)


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _backup_corrupt(path: Path) -> None:
    backup = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
    try:
        os.replace(path, backup)
        logger.error("Moved corrupt persistence file %s to %s", path, backup)
    except OSError:
        logger.exception("Could not move corrupt persistence file %s", path)


def load_json(filepath: str | Path) -> dict | list | None:
    path = Path(filepath)
    lock_file = None
    try:
        if not path.exists():
            return None
        if fcntl is not None:
            lock_file = open(_lock_path(path), "a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        _backup_corrupt(path)
        return None
    except (OSError, UnicodeError):
        return None
    finally:
        if lock_file is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()


def save_json(filepath: str | Path, data: dict | list) -> bool:
    temp_path: str | None = None
    lock_file = None
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is not None:
            lock_file = open(_lock_path(path), "a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            logger.warning("Could not fsync persistence directory %s", path.parent)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
        if lock_file is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()


def load_tracks_from_cache(cache_path: str | Path) -> list[str] | None:
    data = load_json(cache_path)
    if not isinstance(data, dict):
        return None
    tracks = [t["path"] for t in data.get("tracks", []) if isinstance(t, dict) and "path" in t]
    return tracks if tracks else None
