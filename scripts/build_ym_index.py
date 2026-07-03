#!/usr/bin/env python3
"""Build YM local index — scans archiwum/ym/ for .ym files.

Output: ym_cache_local.json with relative paths, file sizes, and categories.

Usage:
    python build_ym_index.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = ROOT_DIR / "archiwum" / "ym"
OUTPUT = ROOT_DIR / "ym_cache_local.json"

COLLECTIONS = {
    "bulba_v5": "Bulba YM Archive v5 — Atari ST YM2149",
    "bulba_1997": "Bulba YM 1997-1998 — Atari ST YM music",
    "faveym": "CyBeR Goth's YMs — curated selection",
    "vtx_etc": "VTX + YM miscellaneous",
    "modland": "Modland FTP — YM modules collection",
}


def main() -> None:
    entries: list[dict] = []
    total = 0
    for subdir, desc in COLLECTIONS.items():
        d = ARCHIVIUM / subdir
        if not d.exists():
            print(f"[SKIP] {subdir} — directory not found")
            continue
        files = sorted(d.rglob("*.[yY][mM]"))
        count = 0
        for f in files:
            rel = str(f.relative_to(ARCHIVIUM))
            size = os.path.getsize(f)
            entries.append({"path": rel, "size": size, "collection": subdir})
            count += 1
        print(f"[OK] {subdir}: {count} YM files — {desc}")
        total += count

    cache = {"version": 1, "total": total, "tracks": entries}
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    print(f"\n[DONE] Saved {total} tracks to {OUTPUT}")


if __name__ == "__main__":
    main()
