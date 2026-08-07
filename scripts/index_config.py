"""Shared configuration for local index builders."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

SYSTEM_METADATA_NAMES = {".ds_store", "desktop.ini", "thumbs.db", ".localized"}


def is_junk_path(path: Path) -> bool:
    """Return whether *path* is archive metadata, hidden content, or empty.

    The name checks intentionally inspect every path component, so a playable
    extension inside ``__MACOSX/`` or another hidden directory is still
    rejected.  Size is checked only for existing regular files.
    """
    for part in path.parts:
        lowered = part.lower()
        if lowered == "__macosx" or lowered in SYSTEM_METADATA_NAMES:
            return True
        if part not in {".", ".."} and part.startswith("."):
            return True
    try:
        return path.is_file() and path.stat().st_size == 0
    except OSError:
        return True


def is_track_file(path: Path, extensions: set[str] | frozenset[str] | tuple[str, ...]) -> bool:
    """Return whether *path* is a non-empty, non-junk music file of an allowed type."""
    normalized_extensions = {ext.lower().lstrip(".") for ext in extensions}
    try:
        return (
            path.is_file()
            and not is_junk_path(path)
            and path.suffix.lower().lstrip(".") in normalized_extensions
        )
    except OSError:
        return False


def remove_junk_paths(root: Path) -> int:
    """Remove junk extracted below *root* and return the number of entries removed."""
    removed = 0
    try:
        paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    except OSError:
        return removed
    for path in paths:
        if not is_junk_path(path):
            continue
        try:
            if path.is_symlink() or not path.is_dir():
                path.unlink(missing_ok=True)
            else:
                shutil.rmtree(path)
            removed += 1
        except OSError:
            continue
    return removed


def load_archive_root(root_dir: Path) -> Path:
    config_path = root_dir / "config.yaml"
    if not config_path.exists():
        return root_dir / "archiwum"
    with open(config_path, encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}
    archive = data.get("archive", {}) if isinstance(data, dict) else {}
    configured = archive.get("path", "archiwum") if isinstance(archive, dict) else "archiwum"
    path = Path(configured) if isinstance(configured, str) and configured else Path("archiwum")
    return path if path.is_absolute() else root_dir / path
