"""Shared configuration for local index builders."""

from __future__ import annotations

from pathlib import Path

import yaml


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
