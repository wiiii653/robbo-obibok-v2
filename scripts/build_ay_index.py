#!/usr/bin/env python3
"""Build AY local index from the configured archive root.

Output: ay_cache_local.json with relative paths, file sizes, and categories.

Usage:
    python build_ay_index.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from index_config import load_archive_root

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = load_archive_root(ROOT_DIR) / "ay"
OUTPUT = ROOT_DIR / "ay_cache_local.json"

SUBDIRS = {
    "aygor": "AYGOR — Original AY compositions",
    "ironfist": "Ironfist's AY Collection — Game rips",
    "tr_songs": "Tr_Songs v6.7 — ZX Spectrum Tracker Music",
    "solo_cpc": "SoLOCPC — Amstrad CPC AY Collection",
    "ts_music": "Turbo Sound Music Collection v3.1",
    "bulba": "Bulba's AY rebuilt collection",
}


def main() -> None:
    entries: list[dict] = []
    total = 0
    for subdir, desc in SUBDIRS.items():
        d = ARCHIVIUM / subdir
        if not d.exists():
            print(f"[SKIP] {subdir} — directory not found")
            continue
        files = sorted(d.rglob("*.ay"))
        count = 0
        for f in files:
            rel = str(f.relative_to(ARCHIVIUM))
            size = os.path.getsize(f)
            entries.append({"path": rel, "size": size, "collection": subdir})
            count += 1
        print(f"[OK] {subdir}: {count} .ay files — {desc}")
        total += count

    cache = {"version": 1, "total": total, "tracks": entries}
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    print(f"\n[DONE] Saved {total} tracks to {OUTPUT}")


if __name__ == "__main__":
    main()
