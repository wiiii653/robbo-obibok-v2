#!/usr/bin/env python3
"""Convert v1 caches to v2 format for robbo-obibok-v2."""
import json
import os
import sys

V1 = "/home/boruta/robbo-obibok"
V2 = "/home/boruta/robbo-obibok-v2"

pairs = {
    "asma_cache_local.json": f"{V1}/asma_cache_local.json",
    "hvsc_cache_local.json": f"{V1}/hvsc_cache_local.json",
    "ay_cache_local.json": f"{V1}/ay_cache.json",
    "ym_cache_local.json": f"{V1}/ym_cache.json",
    "tiny_cache_local.json": f"{V1}/tiny_cache.json",
    "kgen_cache_local.json": f"{V1}/kgen_cache.json",
    "modarchive_cache_local.json": f"{V1}/modarchive_cache.json",
}

for dst_name, src_path in pairs.items():
    dst = os.path.join(V2, dst_name)
    if not os.path.exists(src_path):
        print(f"SKIP {dst_name}: {src_path} not found")
        continue

    with open(src_path) as f:
        data = json.load(f)

    if isinstance(data, dict) and "tracks" in data:
        print(f"OK   {dst_name}: already v2 format ({len(data['tracks'])} tracks)")
        continue
    elif isinstance(data, list):
        paths = data
    elif isinstance(data, dict):
        paths = list(data.keys())
    else:
        print(f"ERR  {dst_name}: unknown format {type(data).__name__}")
        continue

    wrapped = {"tracks": [{"path": p} for p in paths]}
    with open(dst, "w") as f:
        json.dump(wrapped, f, indent=2)
    print(f"OK   {dst_name}: {len(paths)} tracks converted")

print("\nDone.")
