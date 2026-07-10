#!/usr/bin/env python3
"""Build Tiny Music local index from the configured archive root.

Output: tiny_cache_local.json with relative paths, file sizes, and names.

Usage:
    python build_tiny_index.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from index_config import load_archive_root

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = load_archive_root(ROOT_DIR) / "tiny"
OUTPUT = ROOT_DIR / "tiny_cache_local.json"

TRACK_EXTENSIONS = {"mod", "xm", "it", "s3m", "med", "dmf", "mo3", "mptm"}


def main() -> None:
    entries: list[dict] = []
    mods_dir = ARCHIVIUM / "mods"
    if not mods_dir.is_dir():
        print(f"[SKIP] {mods_dir} — directory not found")
        return

    for root, dirs, files in os.walk(mods_dir):
        for f in sorted(files):
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in TRACK_EXTENSIONS:
                full = Path(root) / f
                rel = str(full.relative_to(ARCHIVIUM))
                size = os.path.getsize(full)
                entries.append(
                    {
                        "path": rel,
                        "name": f.rsplit(".", 1)[0],
                        "size": size,
                    }
                )

    cache = {"version": 1, "total": len(entries), "tracks": entries}
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    print(f"[DONE] Saved {len(entries)} tracks to {OUTPUT}")


if __name__ == "__main__":
    main()
