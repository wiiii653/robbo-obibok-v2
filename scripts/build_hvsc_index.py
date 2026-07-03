#!/usr/bin/env python3
"""Build HVSC local index — scans archiwum/hvsc/C64Music/ for .sid files.

Output: hvsc_cache_local.json with relative paths, file sizes, and categories.

Usage:
    python build_hvsc_index.py

The generated cache is used by robbo in local-only mode (no internet download).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = ROOT_DIR / "archiwum" / "hvsc" / "C64Music"
OUTPUT = ROOT_DIR / "hvsc_cache_local.json"

CONTENT_DIRS = ["DEMOS", "GAMES", "MUSICIANS"]


def main() -> None:
    entries: list[dict] = []
    total = 0
    for subdir in CONTENT_DIRS:
        d = ARCHIVIUM / subdir
        if not d.exists():
            print(f"[SKIP] {subdir}/ — directory not found")
            continue
        files = sorted(d.rglob("*.sid"))
        files += sorted(d.rglob("*.SID"))
        seen: set[str] = set()
        unique_files = []
        for f in files:
            p = str(f)
            if p not in seen:
                seen.add(p)
                unique_files.append(f)
        count = 0
        for f in unique_files:
            rel = str(f.relative_to(ARCHIVIUM))
            size = os.path.getsize(f)
            entries.append({"path": rel, "size": size, "collection": subdir})
            count += 1
        print(f"[OK] {subdir}/: {count} .sid files")
        total += count

    cache = {"version": 1, "total": total, "tracks": entries}
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    print(f"\n[DONE] Saved {total} tracks to {OUTPUT}")


if __name__ == "__main__":
    main()
