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


def is_safe_track_path(path: object) -> bool:
    """Return whether path is a non-empty, relative, non-escaping track path."""
    if not isinstance(path, str) or not path.strip():
        return False
    if path.startswith(("/", "\\")) or ":" in path:
        return False
    parts = path.replace("\\", "/").split("/")
    return ".." not in parts and all(part not in ("", ".") for part in parts)


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def ensure_safe_directory(directory: str | Path, root_dir: str | Path) -> bool:
    """Create a persistence directory only when it resolves beneath its root.

    Atomic replacement protects a file itself, but not a directory replaced by
    a symlink.  Validate every component before creating it and again after
    creation, which keeps normal persistence inside the configured root.
    """
    root = Path(root_dir).absolute()
    target = Path(directory).absolute()
    if not _is_within(target, root):
        logger.warning("Refusing persistence directory outside root: %s (root %s)", target, root)
        return False
    try:
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve()
        relative_parts = target.relative_to(root).parts
        current = root
        for part in relative_parts:
            current /= part
            if not _is_within(current.resolve(strict=False), resolved_root):
                logger.warning(
                    "Refusing persistence directory resolving outside root: %s (root %s)",
                    current.resolve(strict=False),
                    resolved_root,
                )
                return False
            current.mkdir(exist_ok=True)
            if not _is_within(current.resolve(), resolved_root):
                logger.warning(
                    "Refusing persistence directory resolving outside root: %s (root %s)",
                    current.resolve(),
                    resolved_root,
                )
                return False
    except OSError:
        logger.warning("Could not create persistence directory %s", target)
        return False
    return True


def _validate_persistence_path(path: Path, root_dir: str | Path | None) -> bool:
    root = Path(root_dir).absolute() if root_dir is not None else path.parent.absolute()
    if not ensure_safe_directory(path.parent, root):
        return False
    resolved_parent = path.parent.resolve()
    resolved_root = root.resolve()
    if not _is_within(resolved_parent, resolved_root):
        logger.warning(
            "Refusing persistence path outside root: %s (root %s)", resolved_parent, resolved_root
        )
        return False
    return True


def _backup_corrupt(path: Path) -> None:
    backup = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
    try:
        os.replace(path, backup)
        logger.error("Moved corrupt persistence file %s to %s", path, backup)
    except OSError:
        logger.exception("Could not move corrupt persistence file %s", path)


def load_json(filepath: str | Path, *, root_dir: str | Path | None = None) -> dict | list | None:
    path = Path(filepath)
    lock_file = None
    try:
        if not _validate_persistence_path(path, root_dir):
            return None
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


def save_json(
    filepath: str | Path, data: dict | list, *, root_dir: str | Path | None = None
) -> bool:
    temp_path: str | None = None
    lock_file = None
    try:
        path = Path(filepath)
        if not _validate_persistence_path(path, root_dir):
            return False
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


def load_tracks_from_cache(
    cache_path: str | Path, *, root_dir: str | Path | None = None
) -> list[str] | None:
    data = load_json(cache_path, root_dir=root_dir)
    if not isinstance(data, dict):
        return None
    raw_tracks = data.get("tracks", [])
    if not isinstance(raw_tracks, list):
        return None
    tracks = [
        t["path"] for t in raw_tracks if isinstance(t, dict) and is_safe_track_path(t.get("path"))
    ]
    return tracks if tracks else None
