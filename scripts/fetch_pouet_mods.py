#!/usr/bin/env python3
"""Boruta's Modland / Demoscene module downloader.

Pobiera trackery (MOD/XM/IT/S3M) z ftp.modland.com według manifestu JSON.
Może też ściągać pliki z dowolnych URL-i (archive.org, modarchive API).

Tryby:
  --build-manifest [KATALOG]   zbuduj manifest.json z istniejącej struktury
  --manifest manifest.json     pobierz wg manifestu
  --check manifest.json        tylko weryfikacja (bez pobierania)
  --dry-run                    pokaż co by się działo, nic nie pobieraj
  --dest KATALOG               katalog docelowy (domyślnie: katalog skryptu)
  --jobs N                     równoległe połączenia (domyślnie 1)

Manifest:
{
  "modland_base": "ftp://modland.com/pub/modules",
  "artists": [
    {"name": "4-Mat", "format": "Protracker", "files": ["eclipse.mod", ...]},
    {"name": "Necros", "subdir": "ScreamTracker3", "format": "Screamtracker 3", "files": [...]}
  ],
  "direct": [
    {"url": "https://archive.org/download/.../E1M777.xm", "dest": "MBR_Dubmood/E1M777.xm"}
  ]
}
"""

from __future__ import annotations

import argparse
import ftplib
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MODLAND_HOST = "ftp.modland.com"
MODLAND_BASE = "/pub/modules"

# rozszerzenie -> katalog formatu na Modlandzie
FORMAT_DIRS = {
    ".mod": "Protracker",
    ".xm": "Fasttracker 2",
    ".s3m": "Screamtracker 3",
    ".it": "Impulsetracker",
    ".med": "OctaMED",
    ".okt": "OctaMED",
    ".dmf": "Delfin",
    ".mtm": "Multitracker",
}

TRACK_EXTS = tuple(FORMAT_DIRS.keys())


def enc(name: str) -> str:
    """URL-encode nazwy pliku (spacje -> %20, nawiasy -> %28 %29 itd.)."""
    return urllib.parse.quote(name, safe="~")


def decode_name(name: str) -> str:
    """Odkoduj nazwę pliku, gdyby na dysku leżała URL-encoded (stary curl potrafił)."""
    if "%" in name:
        dec = urllib.parse.unquote(name)
        if dec != name:
            return dec
    return name


def artist_path(artist: dict) -> Path:
    p = Path(artist["name"])
    if artist.get("subdir"):
        p = p / artist["subdir"]
    return p


def remote_dir(artist: dict, fmt: str, base: str) -> str:
    remote_name = artist.get("remote_name", artist["name"])
    return f"{base}/{fmt}/{remote_name}"


def remote_path(artist: dict, fname: str, base: str, fmt: str) -> str:
    """Ścieżka FTP dla pliku. ftplib wysyła surowe komendy — prawdziwe spacje,
    nie %20 (curl kodował URL-e, ale raw FTP tego nie rozumie)."""
    d = remote_dir(artist, fmt, base)
    return f"{d}/{fname}"


def file_format(fname: str) -> str | None:
    """Format Modland dla pojedynczego pliku (na podstawie rozszerzenia)."""
    return FORMAT_DIRS.get(Path(fname).suffix.lower())


def ftp_size(path: str) -> int | None:
    """Rozmiar pliku na FTP (SIZE). None gdy nie da się odczytać."""
    ftp = ftplib.FTP(MODLAND_HOST, timeout=20)
    try:
        ftp.login()
        return ftp.size(path)
    except Exception:
        return None
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def download_ftp(remote: str, dest: Path, logger=print, retries: int = 3) -> bool:
    """Pobierz pojedynczy plik FTP z retry i atomic write. Zwraca True gdy OK."""
    last_err = None
    for attempt in range(1, retries + 1):
        ftp = None
        tmp = None
        try:
            ftp = ftplib.FTP(MODLAND_HOST, timeout=30)
            ftp.login()
            size = ftp.size(remote)
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
            got = {"bytes": 0}

            def cb(data: bytes) -> None:
                got["bytes"] += len(data)

            with os.fdopen(fd, "wb") as fh:
                ftp.retrbinary(f"RETR {remote}", lambda d: (fh.write(d), got.__setitem__("bytes", got["bytes"] + len(d)))[0])
            if size is not None and got["bytes"] != size:
                raise IOError(f"rozmiar się nie zgadza: {got['bytes']} != {size}")
            if got["bytes"] == 0:
                raise IOError("pusty plik")
            os.replace(tmp, dest)
            logger(f"  ✓ {dest.name} ({got['bytes']:,} B)")
            return True
        except Exception as exc:
            last_err = exc
            logger(f"  ✗ attempt {attempt}/{retries}: {exc}")
            time.sleep(1.5 * attempt)
        finally:
            if ftp:
                try:
                    ftp.quit()
                except Exception:
                    pass
            if tmp is not None and os.path.exists(tmp):
                os.remove(tmp)
    logger(f"  !! FAILED: {remote} — {last_err}")
    return False


def download_http(url: str, dest: Path, logger=print, retries: int = 3) -> bool:
    """Pobierz przez HTTP(S) z retry i atomic write."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if not data:
                raise IOError("pusty response")
            fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)
            logger(f"  ✓ {dest.name} ({len(data):,} B)")
            return True
        except Exception as exc:
            last_err = exc
            logger(f"  ✗ attempt {attempt}/{retries}: {exc}")
            time.sleep(1.5 * attempt)
    logger(f"  !! FAILED: {url} — {last_err}")
    return False


def already_ok(dest: Path, remote_size: int | None) -> bool:
    """Czy lokalny plik jest już OK (istnieje i rozmiar się zgadza)?"""
    if not dest.exists():
        return False
    if remote_size is None:
        return dest.stat().st_size > 0
    return dest.stat().st_size == remote_size


def build_manifest(root: Path) -> dict:
    """Zbuduj manifest z istniejącej struktury katalogów."""
    manifest = {"modland_base": f"ftp://{MODLAND_HOST}{MODLAND_BASE}", "artists": [], "direct": []}
    for artist_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        files = []
        for f in sorted(artist_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in TRACK_EXTS:
                files.append(decode_name(f.name))
        if files:
            manifest["artists"].append({"name": artist_dir.name, "files": files})
        # podkatalogi formatowe (np. Necros/ScreamTracker3)
        for sub in sorted(p for p in artist_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            sub_files = [decode_name(f.name) for f in sorted(sub.iterdir()) if f.is_file() and f.suffix.lower() in TRACK_EXTS]
            if sub_files:
                manifest["artists"].append(
                    {"name": artist_dir.name, "subdir": sub.name, "files": sub_files}
                )
    return manifest


def fill_formats(manifest: dict) -> None:
    """Uzupełnij format z rozszerzenia pliku, jeśli nie podany wprost."""
    for a in manifest.get("artists", []):
        if not a.get("format"):
            exts = {Path(f).suffix.lower() for f in a["files"]}
            fmt = FORMAT_DIRS.get(next(iter(exts), ""))
            a["format"] = fmt or "Protracker"
            if len(exts) > 1:
                a["format"] = None  # mieszane — wymaga ręcznej decyzji


def run_manifest(manifest: dict, dest_root: Path, jobs: int, dry: bool, check_only: bool, logger=print) -> int:
    fill_formats(manifest)
    base = manifest.get("modland_base", f"ftp://{MODLAND_HOST}{MODLAND_BASE}")
    # base może być "ftp://host/pub/modules" albo goły "/pub/modules"
    if base.startswith("ftp://"):
        base = urllib.parse.urlparse(base).path
    base = base.rstrip("/") or MODLAND_BASE

    tasks = []  # (kind, src, dest)
    for a in manifest.get("artists", []):
        artist_fmt = a.get("format")
        if not artist_fmt:
            mixed = len({file_format(f) for f in a["files"] if file_format(f)}) > 1
            if mixed:
                print(f"  ~ {a['name']}: mieszane formaty — dobieram format per plik")
            else:
                artist_fmt = file_format(a["files"][0]) if a["files"] else None
        for fname in a["files"]:
            fmt = artist_fmt or file_format(fname)
            if not fmt:
                logger(f"  !! pomijam {a['name']}/{fname}: nieznany format")
                continue
            dest = dest_root / artist_path(a) / decode_name(fname)
            remote = remote_path(a, fname, base, fmt)
            tasks.append(("ftp", remote, dest))
    for d in manifest.get("direct", []):
        dest = dest_root / d["dest"]
        tasks.append(("http", d["url"], dest))

    if dry or check_only:
        logger(f"Plan: {len(tasks)} plików -> {dest_root}")
        if dry:
            for kind, src, dest in tasks:
                state = "OK" if already_ok(dest, None if kind == "http" else None) else "BRAK"
                logger(f"  [{state}] {dest.relative_to(dest_root)}  <- {src}")
        return 0

    ok = fail = skip = 0
    logger(f"Pobieram {len(tasks)} plików do {dest_root} (jobs={jobs})...")

    def work(task):
        kind, src, dest = task
        if kind == "ftp":
            remote_size = None
            try:
                remote_size = ftp_size(src)
            except Exception:
                pass
            if already_ok(dest, remote_size):
                return "skip", dest
            return ("ok" if download_ftp(src, dest, logger=quiet) else "fail"), dest
        else:
            if already_ok(dest, None):
                return "skip", dest
            return ("ok" if download_http(src, dest, logger=quiet) else "fail"), dest

    def quiet(*_a, **_k):
        pass

    if jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futures = {ex.submit(work, t): t for t in tasks}
            for fut in as_completed(futures):
                status, dest = fut.result()
                rel = dest.relative_to(dest_root)
                if status == "skip":
                    skip += 1
                    logger(f"  = {rel} (już jest)")
                elif status == "ok":
                    ok += 1
                    logger(f"  ✓ {rel}")
                else:
                    fail += 1
                    logger(f"  ✗ {rel}")
    else:
        for task in tasks:
            kind, src, dest = task
            rel = dest.relative_to(dest_root)
            logger(f"[{rel}]")
            if kind == "ftp":
                remote_size = None
                try:
                    remote_size = ftp_size(src)
                except Exception:
                    pass
                if already_ok(dest, remote_size):
                    skip += 1
                    logger(f"  = już jest ({dest.stat().st_size:,} B)")
                    continue
                if download_ftp(src, dest, logger=logger):
                    ok += 1
                else:
                    fail += 1
            else:
                if already_ok(dest, None):
                    skip += 1
                    logger("  = już jest")
                    continue
                if download_http(src, dest, logger=logger):
                    ok += 1
                else:
                    fail += 1

    logger(f"\nWynik: {ok} pobrane, {skip} pominiete, {fail} bledow.")
    return 0 if fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Downloader modułów demosceny (Modland FTP + HTTP).")
    ap.add_argument("--manifest", type=Path, help="ścieżka do manifestu JSON")
    ap.add_argument("--build-manifest", nargs="?", const=".", type=Path, help="zbuduj manifest.json z katalogu")
    ap.add_argument("--dest", type=Path, help="katalog docelowy (domyślnie katalog skryptu)")
    ap.add_argument("--check", action="store_true", help="tylko weryfikuj, nie pobieraj")
    ap.add_argument("--dry-run", action="store_true", help="pokaż plan, nic nie pobieraj")
    ap.add_argument("--jobs", type=int, default=1, help="równoległe pobierania (domyślnie 1)")
    ap.add_argument("--out-manifest", type=Path, default=Path("manifest.json"), help="nazwa pliku manifestu przy --build-manifest")
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent

    if args.build_manifest is not None:
        root = args.build_manifest if args.build_manifest != Path(".") else script_dir
        if str(args.build_manifest) == ".":
            root = Path(".").resolve()
        man = build_manifest(root)
        man_path = args.out_manifest if args.out_manifest.is_absolute() else script_dir / args.out_manifest
        man_path.write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n")
        total = sum(len(a["files"]) for a in man["artists"])
        print(f"Manifest zapisany: {man_path} ({len(man['artists'])} artystów, {total} plików)")
        return 0

    if args.manifest is None:
        ap.error("podaj --manifest albo --build-manifest")

    man = json.loads(args.manifest.read_text())
    dest = args.dest.resolve() if args.dest else script_dir
    return run_manifest(man, dest, args.jobs, args.dry_run, args.check)


if __name__ == "__main__":
    sys.exit(main())
