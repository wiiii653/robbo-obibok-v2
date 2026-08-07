#!/usr/bin/env python3
"""Build KGen local index from the configured archive root.

Output: kgen_cache_local.json with relative paths, file sizes, and names.

Usage:
    python build_kgen_index.py
"""

from __future__ import annotations

import os
from pathlib import Path

from index_config import is_track_file, load_archive_root, save_json_atomic

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = load_archive_root(ROOT_DIR) / "kgen"
OUTPUT = ROOT_DIR / "kgen_cache_local.json"

TRACK_EXTENSIONS = {"mod", "xm", "it", "s3m"}


def main() -> None:
    entries: list[dict] = []
    total = 0

    for root, dirs, files in os.walk(ARCHIVIUM):
        for f in sorted(files):
            full = Path(root) / f
            if is_track_file(full, TRACK_EXTENSIONS):
                rel = str(full.relative_to(ARCHIVIUM))
                size = os.path.getsize(full)
                entries.append(
                    {
                        "path": rel,
                        "name": f.rsplit(".", 1)[0],
                        "size": size,
                    }
                )
                total += 1

    cache = {"version": 1, "total": total, "tracks": entries}
    save_json_atomic(OUTPUT, cache)
    print(f"[DONE] Saved {total} tracks to {OUTPUT}")


if __name__ == "__main__":
    main()
