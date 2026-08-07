#!/usr/bin/env python3
"""Build Party Legacy local index from the configured archive root.

Output: legacy_cache_local.json with relative paths, names, and sizes.

Ścieżki BEZ prefiksu (relative_to legacy root) — _build_track_path składa
root/legacy/<platform>/<plik> sam (archive_path="legacy").

Usage:
    python build_legacy_index.py
"""

from __future__ import annotations

import os
from pathlib import Path

from index_config import is_track_file, load_archive_root, save_json_atomic

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = load_archive_root(ROOT_DIR) / "legacy"
OUTPUT = ROOT_DIR / "legacy_cache_local.json"

TRACK_EXTENSIONS = {
    "sid",
    "sap",
    "ay",
    "ym",
    "mod",
    "xm",
    "it",
    "s3m",
    "med",
    "dmf",
    "nsf",
    "vgm",
    "vgz",
    "snd",
    "sndh",
}


def main() -> None:
    if not ARCHIVIUM.is_dir():
        print(f"[SKIP] {ARCHIVIUM} — directory not found")
        return

    entries: list[dict] = []
    for root, dirs, files in os.walk(ARCHIVIUM):
        for f in sorted(files):
            full = Path(root) / f
            if is_track_file(full, TRACK_EXTENSIONS):
                # Prefiks "legacy/" (rel do roota archiwum) — jak party/:
                # _build_track_path pierwsza gałąź dedupe i resolver ścieżek
                # rozpoznają kolekcję po prefiksie.
                rel = str(full.relative_to(ARCHIVIUM.parent))
                size = os.path.getsize(full)
                entries.append(
                    {
                        "path": rel,
                        "name": f.rsplit(".", 1)[0],
                        "size": size,
                    }
                )

    cache = {"version": 1, "total": len(entries), "tracks": entries}
    save_json_atomic(OUTPUT, cache)
    print(f"[DONE] Saved {len(entries)} tracks to {OUTPUT}")


if __name__ == "__main__":
    main()
