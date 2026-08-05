#!/usr/bin/env python3
"""Konwerter YM5/YM6 -> AY (ZXAYEMUL) dla kolekcji Atari ST YM.

Dlaczego: audacious 4.6.1 (libgme 0.6.4) nie odtwarza .ym — YM2149 nigdy nie
był w libgme (0.5.5->0.6.4 identyczne), a plugin VTX czyta tylko kontener VTX
(nagłówek AY/YM + dane LHa), nie YM5/6. YM2149 (Atari ST) i AY-3-8912 (ZX) to
ten sam układ — YM->AY to zmiana kontenera bez utraty danych rejestrów.

Format YM5/6 wg ST-Sound (ymformat.html + Ymload.cpp):
  magic "YM5!"/"YM6!" + check "LeOnArD!" + nbFrame(4 BE) + attrib(4 BE)
  + nbDrum(2 BE) + clock(4 BE) + playerRate(2 BE) + loop(4 BE) + skip(2 BE)
  [+ skip bajtów] [+ digidrumy] + song/author/comment (NT-strings) + dane
Dane: 16 B/klatkę (14 rejestrów + 2 extended), opcjonalnie interleaved.
Pliki z bulba_v5/faveym/modland są pakowane LHa (magic "-lh5-") — rozpakowujemy
przez 7z, szukamy pliku YM w środku.

Format AY: "ZXAYEMUL" + wersja(1) + playerFreq(2 LE) + song + author + comment
  + 0x00 0x00 + chiptype(1) + clock(4 LE) + frames(4 LE) + loop(4 LE) + dane.
Dane: 14 B/klatkę (rejestry AY), little-endian.

Użycie:
  python3 scripts/ym_to_ay.py --dest ../archiwum/ym_ay archiwum/ym
  python3 scripts/ym_to_ay.py --check --dest ../archiwum/ym_ay archiwum/ym
  python3 scripts/ym_to_ay.py --dry-run archiwum/ym
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

A_STREAMINTERLEAVED = 1
YM_MAGICS = (b"YM2!", b"YM3!", b"YM3b", b"YM5!", b"YM6!")
CHECK_STRING = b"LeOnArD!"
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


def read_be_u32(buf: bytes, pos: int) -> int:
    return struct.unpack(">I", buf[pos : pos + 4])[0]


def read_be_u16(buf: bytes, pos: int) -> int:
    return struct.unpack(">H", buf[pos : pos + 2])[0]


def read_nt_string(buf: bytes, pos: int) -> tuple[str, int]:
    end = buf.index(0, pos)
    return buf[pos:end].decode("latin-1", "replace"), end + 1


def is_lha(data: bytes) -> bool:
    return any(sig in data[:8] for sig in LHA_SIGNATURES)


def extract_lha(data: bytes, timeout: int = 30, _depth: int = 0) -> bytes:
    """Rozpakowuje archiwum LHa przez 7z i zwraca plik YM z środka.
    Rekurencyjnie — niektóre pliki (Flash Gordon) to LHa w LHa."""
    if _depth > 4:
        raise ValueError("zbyt głębokie zagnieżdżenie LHa")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.ym"
        src.write_bytes(data)
        proc = subprocess.run(
            ["7z", "x", "-y", str(src), f"-o{td}"],
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise ValueError("7z nie rozpakował LHa")
        candidates = sorted(p for p in Path(td).rglob("*") if p.is_file() and p != src)
        # weź pierwszy plik, który faktycznie jest YM (magic lub LHa w środku),
        # niezależnie od rozszerzenia (bulba używa .BI5/.DE/.Y5/.YMA itd.)
        out = None
        for cand in candidates:
            probe = cand.read_bytes()
            if probe[:4] in YM_MAGICS or is_lha(probe):
                out = probe
                break
        if out is None:
            raise ValueError("LHa nie zawiera pliku YM")
        if is_lha(out):  # LHa w LHa — rozpakuj jeszcze raz
            return extract_lha(out, timeout=timeout, _depth=_depth + 1)
        if out[:4] not in YM_MAGICS and out[:2].lower() != b"ym":
            raise ValueError(f"rozpakowany plik nie jest YM: {out[:8]!r}")
        return out


def parse_ym(data: bytes) -> dict:
    if len(data) < 12:
        raise ValueError("za krótki plik YM")
    magic = data[:4]
    if magic not in YM_MAGICS:
        raise ValueError(f"nieznany magic: {magic!r}")

    pos = 4
    check = data[pos : pos + 8]
    pos += 8

    if magic in (b"YM5!", b"YM6!"):
        if check != CHECK_STRING:
            raise ValueError(f"zły check string: {check!r}")
        nb_frame = read_be_u32(data, pos)
        attrib = read_be_u32(data, pos + 4)
        nb_drum = read_be_u16(data, pos + 8)
        clock = read_be_u32(data, pos + 10)
        player_rate = read_be_u16(data, pos + 14)
        loop_frame = read_be_u32(data, pos + 16)
        skip = read_be_u16(data, pos + 20)
        pos += 22 + skip
        if nb_drum > 0:
            for _ in range(nb_drum):
                size = read_be_u32(data, pos)
                pos += 4
                pos += size
        song, pos = read_nt_string(data, pos)
        author, pos = read_nt_string(data, pos)
        comment, pos = read_nt_string(data, pos)
        raw = data[pos:]
        frame_size = 16
    else:  # YM2!/YM3!/YM3b: playerFreq (1B) + dane
        player_rate = data[pos]
        pos += 1
        song = author = comment = ""
        clock = 2000000
        loop_frame = 0
        nb_frame = 0
        attrib = 0
        raw = data[pos:]
        frame_size = 14

    if attrib & A_STREAMINTERLEAVED:
        if nb_frame == 0 or len(raw) < nb_frame * frame_size:
            raise ValueError("zły rozmiar danych interleaved")
        planes = [raw[j * nb_frame : (j + 1) * nb_frame] for j in range(frame_size)]
        raw = b"".join(bytes((planes[i][j],)) for j in range(nb_frame) for i in range(frame_size))

    if frame_size == 16:
        if len(raw) % 16 != 0:
            raw = raw[: len(raw) - (len(raw) % 16)]
        regdata = b"".join(raw[i : i + 14] for i in range(0, len(raw), 16))
    else:
        regdata = raw

    return {
        "song": song,
        "author": author,
        "comment": comment,
        "player_rate": player_rate or 50,
        "clock": clock or 1773400,
        "loop_frame": loop_frame,
        "regdata": regdata,
        "nb_frame": len(regdata) // 14,
    }


def build_ay(meta: dict) -> bytes:
    # WAŻNE: GME (console.so) czyta bajt na offsecie 16 jako max_track
    # (liczbę subtracków, maskując do dolnych 4 bitów). Jeśli w nagłówku są
    # pełne stringi song/author/comment, na offsecie 16 ląduje środek nazwy
    # (np. 'S' z "Laser Squad" = 0x53 → 4 tracki) i GME krzyczy
    # "Missing track data". Dlatego stringi są puste — wtedy na offsecie 16
    # jest chiptype (0 = AY) i GME widzi 1 track. Metadane YM i tak żyją
    # w cache i oryginalnych plikach .ym.
    frames = meta["nb_frame"]
    header = b"ZXAYEMUL" + bytes([1])
    header += struct.pack("<H", meta["player_rate"])
    header += b"\x00"  # song (pusty)
    header += b"\x00"  # author (pusty)
    header += b"\x00"  # comment (pusty)
    header += b"\x00\x00"
    header += bytes([0])  # chiptype: 0 = AY (offset 16)
    header += struct.pack("<I", meta["clock"])
    header += struct.pack("<I", frames)
    header += struct.pack("<I", meta["loop_frame"])
    return header + meta["regdata"]


def convert_file(src: Path) -> tuple[Path, bytes, dict]:
    """Zwraca (dest_rel, ay_bytes, meta). Rzuca ValueError na błędzie."""
    data = src.read_bytes()
    if is_lha(data):
        data = extract_lha(data)
    meta = parse_ym(data)
    return src, build_ay(meta), meta


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="YM5/6 -> AY converter (ST-Sound spec)")
    ap.add_argument("src", nargs="+", help="pliki .ym lub katalog z archiwum YM")
    ap.add_argument(
        "--dest", type=Path, required=True, help="katalog docelowy (zachowuje strukturę)"
    )
    ap.add_argument("--jobs", type=int, default=4, help="liczba wątków")
    ap.add_argument("--check", action="store_true", help="tylko sprawdź co by się zmieniło")
    ap.add_argument("--dry-run", action="store_true", help="pokaż plan, nic nie pisz")
    ap.add_argument("--force", action="store_true", help="nadpisuj istniejące pliki AY")
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

    done = 0
    fails: list[tuple[Path, str]] = []

    def work(src: Path):
        try:
            return convert_file(src)
        except Exception as exc:  # noqa: BLE001
            return src, None, {"error": str(exc)}

    if args.check or args.dry_run:
        # tylko zaplanuj (bez 7z w dry-run? lepiej z 7z dla dokładności w --check)
        for src in files:
            dest = (
                args.dest / src.relative_to(src.anchor if False else _common_root(files))
            ).with_suffix(".ay")
            print(f"  {'[check]' if args.check else '[dry]'} {src} -> {dest}")
        return 0

    dest_root = args.dest
    # wspólny korzeń wejścia (gdy podano katalog, używamy względem niego)
    src_paths = [Path(s).resolve() for s in args.src]
    roots = [p for p in src_paths if p.is_dir()]
    common = roots[0] if roots else (files[0].parent if files else Path("."))

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(work, src): src for src in files}
        for fut in as_completed(futures):
            src, ay_bytes, meta = fut.result()
            if ay_bytes is None:
                fails.append((src, str(meta.get("error", "?"))))
                print(f"  !! {src.name}: {meta.get('error', '?')}")
                continue
            try:
                rel = src.relative_to(common)
            except ValueError:
                # źródło spoza wspólnego korzenia (np. plik podany wprost)
                rel = Path(*src.parts[1:]) if src.is_absolute() else src
            dest = (dest_root / rel).with_suffix(".ay")
            if dest.exists() and not args.force:
                print(f"  = {rel} (istnieje)")
                done += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".ay.tmp")
            tmp.write_bytes(ay_bytes)
            tmp.replace(dest)
            print(f"  {rel}: {src.stat().st_size} -> {len(ay_bytes)} B, {meta['nb_frame']} klatek")
            done += 1

    print(f"\nOK: {done}, FAIL: {len(fails)}")
    if fails:
        for p, err in fails[:15]:
            print(f"  FAIL {p}: {err}")
    return 0 if not fails else 1


def _common_root(files: list[Path]) -> Path:
    # najdłuższy wspólny prefix katalogów
    parts = [list(p.resolve().parts) for p in files]
    common = parts[0]
    for p in parts[1:]:
        i = 0
        while i < len(common) and i < len(p) and common[i] == p[i]:
            i += 1
        common = common[:i]
    return Path(*common)


if __name__ == "__main__":
    sys.exit(main())
