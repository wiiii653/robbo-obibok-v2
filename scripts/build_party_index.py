#!/usr/bin/env python3
"""Build Party Music local index from the configured archive root.

Output: party_cache_local.json with relative paths, names, and sizes.

Usage:
    python build_party_index.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from index_config import load_archive_root

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVIUM = load_archive_root(ROOT_DIR) / "party"
OUTPUT = ROOT_DIR / "party_cache_local.json"

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
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in TRACK_EXTENSIONS:
                full = Path(root) / f
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
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(OUTPUT.parent), prefix=f".{OUTPUT.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        os.replace(tmp, OUTPUT)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print(f"[DONE] Saved {len(entries)} tracks to {OUTPUT}")


if __name__ == "__main__":
    main()
