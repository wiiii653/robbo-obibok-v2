#!/usr/bin/env python3
"""Build Pouet/Demozoo (scena) local index from the configured archive root.

Output: pouet_cache_local.json with relative paths, file sizes, and names.

Usage:
    python build_pouet_index.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from index_config import load_archive_root

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = load_archive_root(ROOT_DIR) / "pouet"
OUTPUT = ROOT_DIR / "pouet_cache_local.json"

TRACK_EXTENSIONS = {"mod", "xm", "it", "s3m", "med", "dmf"}


def main() -> None:
    if not ARCHIVIUM.is_dir():
        print(f"[SKIP] {ARCHIVIUM} — directory not found")
        return

    entries: list[dict] = []
    for root, dirs, files in os.walk(ARCHIVIUM):
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
