#!/usr/bin/env python3
"""Konwerter YM5/6 -> OGG przez ym2wav (ST-Sound) + ffmpeg.

Dlaczego: audacious 4.6.1 (libgme 0.6.4) nie odtwarza .ym — libgme nigdy nie
miał YM2149, a VTX czyta tylko kontener VTX. YM->AY (prosty rejestrowy) też
nie działa — GME czyta AY wyłącznie jako format Z80-embedded (z kodem playera),
bez fallbacku na surowe rejestry. Jedyna pewna droga to ST-Sound (ym2wav):
YM -> WAV -> OGG (ffmpeg). OGG gra przez ffmpeg w audacious bez żadnych
wtyczek chiptune.

Pipeline na plik:
  1. Rozpakuj LHa przez 7z (jeśli .ym to archiwum -lh5-), znajdź YM w środku
  2. ym2wav <ym> <wav>  (ST-Sound, Arnaud Carre)
  3. ffmpeg -i <wav> -c:a libvorbis -q:a 4 <ogg>
  4. Atomic rename .ogg; WAV ląduje w tempdir (kasowany)

Wonderboy (xx-lh5-xx, 7z nie czyta) też obsługuje ym2wav bezpośrednio — ST-Sound
capuje zepsuty packedSize. YMT (YM Tracker, sample'owy) crashuje ST-Sound —
pomijamy (to nie chiptune). MIX (digi-mix) — też sample'owy, ale ST-Sound radzi.

Użycie:
  python3 scripts/ym_to_ogg.py archiwum/ym --dest archiwum/ym_ogg --jobs 8
  python3 scripts/ym_to_ogg.py --check archiwum/ym --dest archiwum/ym_ogg
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

YM_MAGICS = (b"YM2!", b"YM3!", b"YM3b", b"YM5!", b"YM6!")
LHA_SIGNATURES = (
    b"-lh0-",
    b"-lh1-",
    b"-lh2-",
    b"-lh3-",
    b"-lh4-",
    b"-lh5-",
    b"-lh6-",
    b"-lh7-",
    b"-lhd-",
    b"-lzs-",
    b"-lz4-",
    b"-lz5-",
)


def is_lha(data: bytes) -> bool:
    return any(sig in data[:8] for sig in LHA_SIGNATURES)


def extract_lha(data: bytes, timeout: int = 60) -> bytes:
    """Rozpakowuje LHa przez 7z; rekurencyjnie dla LHa-w-LHa (Flash Gordon)."""
    return _extract_lha(data, timeout, 0)


def _extract_lha(data: bytes, timeout: int, depth: int) -> bytes:
    if depth > 4:
        raise ValueError("zbyt głębokie zagnieżdżenie LHa")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.ym"
        src.write_bytes(data)
        proc = subprocess.run(
            ["7z", "x", "-y", str(src), f"-o{td}"], capture_output=True, timeout=timeout
        )
        if proc.returncode != 0:
            raise ValueError("7z nie rozpakował LHa")
        candidates = sorted(p for p in Path(td).rglob("*") if p.is_file() and p != src)
        out = None
        for cand in candidates:
            probe = cand.read_bytes()
            if probe[:4] in YM_MAGICS or is_lha(probe):
                out = probe
                break
        if out is None:
            raise ValueError("LHa nie zawiera pliku YM")
        if is_lha(out):
            return _extract_lha(out, timeout, depth + 1)
        return out


def ym2wav_single(src: Path, wav: Path, timeout: int = 300) -> None:
    """ym2wav z pliku .ym (obsługuje też Wonderboy bez rozpakowania)."""
    proc = subprocess.run(["ym2wav", str(src), str(wav)], capture_output=True, timeout=timeout)
    if proc.returncode != 0 or not wav.exists() or wav.stat().st_size == 0:
        raise ValueError(f"ym2wav nie udało się (rc={proc.returncode})")


def convert_one(src: Path, dest: Path, keep_wav: bool = False) -> tuple[int, int]:
    """Konwertuje jeden .ym -> .ogg. Zwraca (rozmiar_ym, rozmiar_ogg)."""
    data = src.read_bytes()
    ym_src = src
    try:
        if is_lha(data):
            try:
                inner = extract_lha(data)
            except Exception:
                # Wonderboy: 7z nie czyta (xx-lh5-xx), ale ym2wav (ST-Sound)
                # capuje zepsuty packedSize i depackuje sam. Zostawiamy oryginał.
                inner = None
            if inner is not None:
                with tempfile.NamedTemporaryFile(suffix=".ym", delete=False) as tf:
                    tf.write(inner)
                    ym_src = Path(tf.name)
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "out.wav"
            ym2wav_single(ym_src, wav)
            ogg = Path(td) / "out.ogg"
            ff = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-threads",
                    "1",
                    "-i",
                    str(wav),
                    "-c:a",
                    "libvorbis",
                    "-q:a",
                    "4",
                    str(ogg),
                ],
                capture_output=True,
                timeout=300,
            )
            if ff.returncode != 0 or not ogg.exists():
                raise ValueError("ffmpeg nie skonwertował WAV -> OGG")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".ogg.tmp")
            tmp.write_bytes(ogg.read_bytes())
            tmp.replace(dest)
            if keep_wav:
                wav_dest = dest.with_suffix(".wav")
                wav_dest.write_bytes(wav.read_bytes())
            return src.stat().st_size, ogg.stat().st_size
    finally:
        if ym_src != src:
            try:
                os.unlink(ym_src)
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description="YM -> OGG via ym2wav + ffmpeg")
    ap.add_argument("src", nargs="+", help="pliki .ym lub katalog")
    ap.add_argument("--dest", type=Path, required=True, help="katalog docelowy")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--check", action="store_true", help="tylko policz co trzeba")
    ap.add_argument("--force", action="store_true", help="nadpisuj istniejące")
    ap.add_argument("--keep-wav", action="store_true", help="zostaw też WAV")
    args = ap.parse_args()

    files: list[Path] = []
    for s in args.src:
        p = Path(s).resolve()
        if p.is_dir():
            files.extend(p.rglob("*.[yY][mM]"))
        elif p.is_file():
            files.append(p)
    files = sorted(set(files))
    print(f"Znaleziono {len(files)} plików YM")

    src_paths = [Path(s).resolve() for s in args.src]
    roots = [p for p in src_paths if p.is_dir()]
    common = roots[0] if roots else (files[0].parent if files else Path("."))

    if args.check:
        todo = 0
        for src in files:
            rel = src.relative_to(common)
            dest = (args.dest / rel).with_suffix(".ogg")
            if args.force or not dest.exists():
                todo += 1
        print(f"Do konwersji: {todo} / {len(files)}")
        return 0

    done = 0
    fails: list[tuple[Path, str]] = []

    def work(src: Path):
        try:
            rel = src.relative_to(common)
        except ValueError:
            rel = Path(*src.parts[1:]) if src.is_absolute() else src
        dest = (args.dest / rel).with_suffix(".ogg")
        if dest.exists() and not args.force:
            return None
        try:
            ym_size, ogg_size = convert_one(src, dest, args.keep_wav)
            return ("ok", src, ym_size, ogg_size)
        except Exception as exc:  # noqa: BLE001
            return ("err", src, str(exc), None)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(work, src): src for src in files}
        for fut in as_completed(futures):
            res = fut.result()
            if res is None:
                continue
            kind = res[0]
            if kind == "err":
                _, src, err, _ = res
                fails.append((src, err))
                print(f"  !! {src.name}: {err}")
                continue
            _, src, ym_size, ogg_size = res
            done += 1
            print(f"  {src.name}: {ym_size} -> {ogg_size} B")

    print(f"\nOK: {done}, FAIL: {len(fails)}")
    if fails:
        for p, err in fails[:15]:
            print(f"  FAIL {p}: {err}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
