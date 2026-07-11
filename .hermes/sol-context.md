# Robbo Obibok v2 — Playback gap analysis

## Problem
Between queue positions 92 and 95 (0-indexed), 2 tracks were silently skipped:
- [93] `193745_b08174eb6c99_mydream2.xm` (ModArchive collection) → play_file: FAILED after 3 attempts
- [94] `Unknown/AMS/Ghostbusters.sap` (ASMA collection) → REFUSED — SAP TYPE D not supported

User sees positions 93-96 (1-indexed). The queue has 110 tracks total.

## Log evidence (journalctl -u robbo-obibok)
```
02:36:42 Track ended (output drop 160->0) for Paula Haunt track
02:36:42 193745_b08174eb6c99_mydream2.xm → add=True play=True but FAILED after 3 attempts
02:36:43 Unknown/AMS/Ghostbusters.sap → REFUSED (SAP TYPE D not supported)
02:36:43 mods/pouet-demozoo/Necros/ScreamTracker3/mechanism eight.s3m → played SUCCESSFULLY
```

## Many other failures in same session
1. `52001_9ab67d332910_mission.xm` — FAILED, file EXISTS on disk
2. `Quad - Open Your Soul.it` — FAILED, file EXISTS on disk
3. `C64Music/MUSICIANS/D/Dokken/Entropy_part_1.sid` — FAILED, `exists=False` (wrong path!)
4. `C64Music/MUSICIANS/G/Gregfeel/Blowers.sid` — FAILED, `exists=False` (wrong path!)
5. `158746_cb74a9febfff_whiskas_-_airwolf.mod` — FAILED, file EXISTS
6. `134896_fa133d1791cb_horizon99_lo0p.xm` — FAILED, file EXISTS
7. `166229_7beccbe7802e_interphace_-_overture.mod` — FAILED, file EXISTS

## HVSC double-path bug
HVSC collection in `models.py`: `archive_path="hvsc/C64Music"`
HVSC cache stores: `MUSICIANS/A/Ace64/Tune_19.sid` (without C64Music/)
RESOLVED path: `archiwum/hvsc/C64Music/MUSICIANS/...` — CORRECT ✓

But the saved QUEUE has entries like: `C64Music/MUSICIANS/A/Ace64/Tune_19.sid` (with C64Music/ prefix)
RESOLVED path with queue prefix: `archiwum/hvsc/C64Music/C64Music/MUSICIANS/...` — DOUBLE! ✗

Yet early in the session some HVSC tracks played fine. How?

## ModArchive cache/queue path mismatch
ModArchive cache stores tracks with paths like:
- `cache/193745_b08174eb6c99_mydream2.xm`
- `cache/52001_9ab67d332910_mission.xm`
- `extracted/1064046431_perforation_overture.xm`
- `1064046431_perforation_overture.xm` (flat)

But the saved queue has: `193745_b08174eb6c99_mydream2.xm` (without `cache/` prefix)
RESOLVED path: `archiwum/modarchive/193745_b08174eb6c99_mydream2.xm` — file EXISTS but Audacious won't play it.

Same for: 52001, 158746, 134896, 166229 — all in queue without `cache/` prefix, all EXIST on disk at the resolved path, but Audacious rejects them.

## Key code paths
- `playback.py:_play_track_unlocked()` — tries up to 5 tracks, skips on failure
- `play_file()` in `audio.py` — audtool playlist-addurl + playback-play, 3 retries
- `_resolve_track_path()` in `playback.py` — Path(root_dir, archive_root, col.archive_path, track)
- `load_tracks_from_cache()` in `persistence.py` — extracts `t["path"]` from cache JSON
- `can_restore_queue()` in `queue.py` — checks `all(item in tracks for item in queue)` — would fail on prefix mismatch

## Goals
1. Root cause analysis — why are these tracks being skipped?
2. Is it a cache/queue path mismatch that accumulated over restarts?
3. Why do files that exist on disk fail to play in Audacious?
4. Are there other systemic issues causing silent skips?
