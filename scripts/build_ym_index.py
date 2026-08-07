#!/usr/bin/env python3
"""Build YM local index from the configured archive root.

Output: ym_cache_local.json with relative paths, file sizes, and categories.

Usage:
    python build_ym_index.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from index_config import is_track_file, load_archive_root

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = load_archive_root(ROOT_DIR) / "ym"
OUTPUT = ROOT_DIR / "ym_cache_local.json"

COLLECTIONS = {
    "bulba_v5": "Bulba YM Archive v5 — Atari ST YM2149 (natywnie przez ym.so)",
    "bulba_1997": "Bulba YM 1997-1998 — Atari ST YM music (natywnie przez ym.so)",
    "faveym": "CyBeR Goth's YMs — curated selection (natywnie przez ym.so)",
    "vtx_etc": "VTX + YM miscellaneous (natywnie przez ym.so)",
    "modland": "Modland FTP — YM modules collection (natywnie przez ym.so)",
}


def main() -> None:
    entries: list[dict] = []
    total = 0
    for subdir, desc in COLLECTIONS.items():
        d = ARCHIVIUM / subdir
        if not d.exists():
            print(f"[SKIP] {subdir} — directory not found")
            continue
        # Case-insensitive: collection has mixed .ym / .YM (bulba_1997, faveym, vtx_etc).
        files = [path for path in sorted(d.rglob("*")) if is_track_file(path, {"ym"})]
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
