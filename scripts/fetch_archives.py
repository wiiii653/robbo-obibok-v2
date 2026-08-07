#!/usr/bin/env python3
"""Boruta's Robbo v2 archive downloader — pobiera i rozpakowuje wszystkie archiwa.

Archiwa obsługiwane:
  hvsc        C64 SID — High Voltage SID Collection (release 7z z hvsc.c64.org API)
  asma        Atari SAP — asma.atari.org (pełny zip z asmadb)
  ay          ZX Spectrum AY — ay.strangled.net (Tr_Songs, bulba, ironfist)
  ym          Atari ST YM — ay.strangled.net (YM Archive v5, YM, VtxYmEtc, faveym) + Modland FTP
  kgen        Keygen music — keygen-music-pack.zip (GitHub mirror 6512345/keygenmusic)
  modarchive  ModArchive tracker — snapshot textfiles.com (download_modarchive_bulk.py)
  tiny        Demoscene modules — fetch_mods.py (pouet-demozoo-mods repo)

Tryby:
  python3 fetch_archives.py hvsc --check          # sprawdź czy jest najnowszy (API)
  python3 fetch_archives.py hvsc --dry-run        # pokaż co by się pobierało
  python3 fetch_archives.py ay --dest /tmp/x      # pobierz i rozpakuj do wskazanego celu
  python3 fetch_archives.py all --check           # sprawdź wszystkie
  python3 fetch_archives.py all --build-index     # po pobraniu przebuduj *_cache_local.json

Wymagania: python3, 7z (p7zip), curl. Używa tylko stdlib (urllib) do pobierania.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from index_config import is_track_file, load_archive_root, remove_junk_paths
from party_music_grabber import _validate_archive_members

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
# Ścieżka archiwum z config.yaml (archive.path) — może być absolutna
# (np. /home/boruta/robbo-music) albo względna; env ROBBO_ARCHIVIUM nadal
# nadpisuje, gdy trzeba wskazać inny katalog bez ruszania configu.
ARCHIVIUM = Path(os.environ.get("ROBBO_ARCHIVIUM", str(load_archive_root(PROJECT_ROOT))))
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"


def log(msg: str) -> None:
    print(msg, flush=True)


def http_get(url: str, timeout: int = 60) -> bytes:
    """GET z retry. Zwraca treść."""
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            log(f"    ! retry {attempt}/3: {exc}")
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"GET failed: {url} — {last}")


def http_size(url: str, timeout: int = 30) -> int | None:
    """Rozmiar zdalnego pliku (Content-Length) lub None."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.headers.get("Content-Length", 0)) or None
    except Exception:  # noqa: BLE001
        return None


def download_file(url: str, dest: Path, expected: int | None = None) -> bool:
    """Pobierz plik z retry i atomic write. True gdy OK."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, 4):
        tmp = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if expected and len(data) != expected:
                log(f"    ! rozmiar: {len(data)} != oczekiwany {expected}")
            if not data:
                raise IOError("pusty plik")
            fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)
            return True
        except Exception as exc:  # noqa: BLE001
            last = exc
            if tmp is not None and os.path.exists(tmp):
                os.remove(tmp)
            log(f"    ! retry {attempt}/3: {exc}")
            time.sleep(1.5 * attempt)
    log(f"  !! FAILED: {url} — {last}")
    return False


def extract(archive: Path, dest: Path, strip: int = 0) -> bool:
    """Rozpakuj 7z/zip do dest. strip = ile pierwszych elementów ścieżki usunąć."""
    members = _list_7z_members(archive)
    if members is None or not _validate_archive_members(members):
        log("  !! archiwum nie przeszło walidacji przed rozpakowaniem")
        return False
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["7z", "x", "-y", f"-o{dest}", str(archive)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if res.returncode != 0:
        log(f"  !! 7z fail: {res.stderr[-300:]}")
        return False
    if strip > 0:
        _strip_prefix(dest, strip)
    removed = remove_junk_paths(dest)
    if removed:
        log(f"    usunięto {removed} ścieżek metadanych/pustych plików")
    return True


def _list_7z_members(archive: Path) -> list[tuple[str, int]] | None:
    """List and validate regular 7z members before allowing extraction."""
    try:
        res = subprocess.run(
            ["7z", "l", "-slt", str(archive)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"  !! nie można sprawdzić archiwum: {exc}")
        return None
    if res.returncode != 0:
        log(f"  !! 7z list fail: {res.stderr[-300:]}")
        return None

    listing = res.stdout.partition("----------")[2]
    if not listing:
        log("  !! 7z nie zwrócił listy członków")
        return None
    members: list[tuple[str, int]] = []
    for block in listing.split("\n\n"):
        values = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if not values:
            continue
        name = values.get("Path")
        attributes = values.get("Attributes", "")
        if not name or not attributes:
            log("  !! archiwum zawiera wpis bez pełnych metadanych")
            return None
        mode = attributes.split()[-1] if attributes.split() else ""
        if any(key in values for key in ("Symbolic Link", "Hard Link", "Reparse Point")) or (
            mode and mode[0] not in {"-", "d"}
        ):
            log(f"  !! archiwum zawiera link lub plik specjalny: {name}")
            return None
        try:
            size = int(values.get("Size", "0"))
        except ValueError:
            log(f"  !! archiwum ma nieprawidłowy rozmiar wpisu: {name}")
            return None
        members.append((name, size))
    return members


def _strip_prefix(root: Path, strip: int) -> None:
    """Usuń strip pierwszych elementów z każdej ścieżki (np. asma/ -> ./)."""
    for p in list(root.rglob("*")):
        rel = p.relative_to(root)
        parts = rel.parts
        if len(parts) <= strip:
            continue
        new_rel = Path(*parts[strip:])
        new_path = root / new_rel
        new_path.parent.mkdir(parents=True, exist_ok=True)
        if p.is_dir():
            continue
        if not new_path.exists():
            shutil.move(str(p), str(new_path))
    # posprzątaj puste katalogi z prefixu
    for p in sorted(root.rglob("*"), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            try:
                p.rmdir()
            except OSError:
                pass


# ── definicje archiwów ────────────────────────────────────────────────


def _has_music(dest: Path) -> bool:
    """Czy katalog docelowy zawiera rozpakowane pliki muzyczne (nie samo archiwum)."""
    if not dest.is_dir():
        return False
    try:
        for p in dest.rglob("*"):
            if is_track_file(p, MUSIC_EXTS):
                return True
    except OSError:
        return False
    return False


def _hvsc_package_path(dest: Path, filename: str) -> Path | None:
    """Return a package path only when it remains below the HVSC destination."""
    root = dest.resolve()
    package = (root / filename).resolve()
    return package if package.is_relative_to(root) else None


def hvsc_plan() -> dict:
    """Najnowsza wersja HVSC z oficjalnego API + mirror (boswme.home.xs4all.nl nie żyje)."""
    api = json.loads(http_get("https://hvsc.c64.org/api/v1/version/7z").decode())
    if not isinstance(api, dict):
        log("  !! nieprawidłowa odpowiedź API HVSC")
        return {}
    version = str(api.get("version", ""))
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        log(f"  !! nieprawidłowa wersja HVSC z API: {version!r}")
        return {}
    # oficjalny hosting XS4ALL został zamknięty — pliki serwuje mirror hvsc.brona.dk
    # (struktura katalogów ta sama: /HVSC/HVSC_<wersja>-all-of-them.7z)
    mirror_base = "https://hvsc.brona.dk"
    complete = f"{mirror_base}/HVSC/HVSC_{version}-all-of-them.7z"
    update = f"{mirror_base}/HVSC/HVSC_Update_{version}.7z"
    dest = ARCHIVIUM / "hvsc"
    complete_package = _hvsc_package_path(dest, f"HVSC_{version}-all-of-them.7z")
    update_package = _hvsc_package_path(dest, f"HVSC_Update_{version}.7z")
    if complete_package is None or update_package is None:
        log("  !! niebezpieczna ścieżka pakietu HVSC")
        return {}
    local = dest / "C64Music"
    return {
        "name": "hvsc",
        "version": version,
        "complete_url": complete,
        "update_url": update,
        "dest": dest,
        "local_exists": local.exists(),
    }


def apply_hvsc_update(extract_dir: Path) -> int:
    """Wtop update w C64Music: update/new/* -> MUSICIANS/GAMES/DEMOS, update/fix/* nadpisuje."""
    upd = extract_dir / "update"
    if not upd.exists():
        log("    (brak katalogu update/ — nic do wtopienia)")
        return 0
    moved = 0
    for sub in ("new", "fix"):
        src = upd / sub
        if not src.exists():
            continue
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src)
                dst = extract_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                moved += 1
    log(f"    update wtopiony: {moved} plików (new=587, fix=43 — wg newsów)")
    return moved


def fetch_hvsc(dry: bool, check_only: bool, dest_override: Path | None) -> int:
    plan = hvsc_plan()
    if not plan:
        return 1
    dest = dest_override or plan["dest"]
    local_exists = (dest / "C64Music").exists()
    log(f"  HVSC wersja # {plan['version']}")
    log(f"  complete: {plan['complete_url']}")
    log(f"  update:   {plan['update_url']}")
    log(f"  cel:      {dest} (C64Music istnieje: {local_exists})")
    if dry or check_only:
        return 0
    if local_exists:
        # mamy pełną wersję — pobierz update (mniejsze)
        log("  mamy C64Music — pobieram update:")
        pkg = _hvsc_package_path(dest, f"HVSC_Update_{plan['version']}.7z")
        if pkg is None:
            log("  !! niebezpieczna ścieżka pakietu HVSC")
            return 1
        if download_file(plan["update_url"], pkg):
            extract(pkg, dest / "C64Music")
            log("  update rozpakowany — wtapiam w C64Music/")
            apply_hvsc_update(dest / "C64Music")
        return 0
    log("  brak C64Music — pobieram pełną wersję (duży plik):")
    pkg = _hvsc_package_path(dest, f"HVSC_{plan['version']}-all-of-them.7z")
    if pkg is None:
        log("  !! niebezpieczna ścieżka pakietu HVSC")
        return 1
    if download_file(plan["complete_url"], pkg):
        extract(pkg, dest)
        log("  HVSC rozpakowany")
    return 0


def fetch_asma(dry: bool, check_only: bool, dest_override: Path | None) -> int:
    url = "https://asma.atari.org/asmadb/asma.zip"
    dest = dest_override or (ARCHIVIUM / "asma")
    size = http_size(url)
    log(f"  ASMA: {url} ({size:,} B, lokalnie: {_has_music(dest)})")
    if dry or check_only:
        return 0
    pkg = dest / "asma.zip"
    if download_file(url, pkg, expected=size):
        # asma.zip zawiera asma/... — strip 1 poziom
        extract(pkg, dest, strip=1)
        log("  ASMA rozpakowany (prefix asma/ usunięty)")
    return 0


AY_PACKAGES = [
    ("Tr_Songs.7z", "ay/tr_songs", 0),
    ("bulba_ay.7z", "ay/bulba", 0),
    ("ifist_ay.zip", "ay/ironfist", 0),
    ("YM.7z", "ym/bulba_1997", 0),
    ("YM_Archive_v5.7z", "ym/bulba_v5", 0),
    ("VtxYmEtc.7z", "ym/vtx_etc", 0),
    ("faveym.7z", "ym/faveym", 0),
]

# Rozszerzenia muzyczne, które Robbo gra — służą do oceny, czy katalog
# docelowy ma rozpakowane dane (a nie tylko leżące archiwum).
MUSIC_EXTS = {
    "sid",
    "sap",
    "ay",
    "ym",
    "snd",
    "sndh",
    "nsf",
    "vgm",
    "vgz",
    "mod",
    "xm",
    "it",
    "s3m",
    "med",
    "dmf",
}


def fetch_ay(dry: bool, check_only: bool, dest_override: Path | None) -> int:
    base = "https://ay.strangled.net"
    dest_root = dest_override or ARCHIVIUM
    for fname, rel, strip in AY_PACKAGES:
        url = f"{base}/{fname}"
        dest = dest_root / rel
        size = http_size(url)
        local = dest / fname
        has_data = _has_music(dest)
        log(f"  {fname}: {size:,} B -> {dest} (dane: {has_data}, archiwum: {local.exists()})")
        if dry or check_only:
            continue
        if local.exists():
            log("    = już jest")
            continue
        if download_file(url, local, expected=size):
            extract(local, dest, strip=strip)
            log(f"    ✓ rozpakowano do {dest}")
    return 0


def fetch_kgen(dry: bool, check_only: bool, dest_override: Path | None) -> int:
    # GitHub mirror — pełny backup keygenmusic (zip repo)
    url = "https://codeload.github.com/6512345/keygenmusic/zip/refs/heads/main"
    dest = dest_override or (ARCHIVIUM / "kgen")
    size = http_size(url)
    size_txt = f"{size:,} B" if size else "nieznany"
    log(f"  KGen: {url} ({size_txt}, lokalnie: {_has_music(dest)})")
    if dry or check_only:
        return 0
    pkg = dest / "keygen-music-pack.zip"
    if download_file(url, pkg, expected=size):
        extract(pkg, dest, strip=1)
        log("  KGen rozpakowany")
    return 0


def fetch_modarchive(dry: bool, check_only: bool, dest_override: Path | None) -> int:
    """ModArchive — snapshot z modarchive.textfiles.com (istniejący bulk downloader)."""
    script = SCRIPT_DIR / "download_modarchive_bulk.py"
    if not script.exists():
        log("  !! brak scripts/download_modarchive_bulk.py — skopiuj go z robbo-obibot/")
        return 1
    log("  ModArchive: wywołuję download_modarchive_bulk.py (duży — GB!):")
    if dry or check_only:
        log("    (dry-run/check — bez pobierania)")
        return 0
    env = dict(os.environ)
    if dest_override:
        env["MODARCHIVE_BULK_OUTDIR"] = str(dest_override)
    res = subprocess.run([sys.executable, str(script)], env=env, timeout=60 * 60 * 6)
    return res.returncode


def fetch_tiny(dry: bool, check_only: bool, dest_override: Path | None) -> int:
    """Tiny — demoscene modules via fetch_pouet_mods.py (lokalna kopia w scripts/)."""
    script = SCRIPT_DIR / "fetch_pouet_mods.py"
    manifest = SCRIPT_DIR / "pouet_manifest.json"
    if not script.exists() or not manifest.exists():
        log("  !! brak scripts/fetch_pouet_mods.py lub pouet_manifest.json")
        return 1
    log("  Tiny/Pouet: wywołuję fetch_pouet_mods.py (manifest pouet-demozoo):")
    if dry or check_only:
        log("    (dry-run/check — bez pobierania)")
        return 0
    cmd = [sys.executable, str(script), "--manifest", str(manifest)]
    # domyślny cel: archiwum/pouet (Scena! — osobna kolekcja od 2026-08-07)
    dest = dest_override or (ARCHIVIUM / "pouet")
    cmd += ["--dest", str(dest)]
    res = subprocess.run(cmd, timeout=60 * 60 * 2)
    return res.returncode


FETCHERS = {
    "hvsc": fetch_hvsc,
    "asma": fetch_asma,
    "ay": fetch_ay,
    "kgen": fetch_kgen,
    "modarchive": fetch_modarchive,
    "tiny": fetch_tiny,
}


def build_index(name: str) -> None:
    script = SCRIPT_DIR / f"build_{name}_index.py"
    if not script.exists():
        log(f"  (brak build_{name}_index.py — pomijam)")
        return
    log(f"  przebudowa indeksu: {script.name}")
    subprocess.run([sys.executable, str(script)], timeout=60 * 30)


def main() -> int:
    ap = argparse.ArgumentParser(description="Pobieracz archiwów Robbo v2")
    ap.add_argument(
        "archive", nargs="?", default="all", help="hvsc|asma|ay|kgen|modarchive|tiny|all"
    )
    ap.add_argument("--check", action="store_true", help="tylko sprawdź stan (API/rozmiary)")
    ap.add_argument("--dry-run", action="store_true", help="pokaż plan, nic nie pobieraj")
    ap.add_argument("--dest", type=Path, help="nadpisz katalog docelowy")
    ap.add_argument("--build-index", action="store_true", help="po pobraniu przebuduj cache")
    args = ap.parse_args()

    targets = list(FETCHERS) if args.archive == "all" else [args.archive]
    bad = [t for t in targets if t not in FETCHERS]
    if bad:
        ap.error(f"nieznane archiwum: {bad}")

    rc = 0
    for name in targets:
        log(f"\n=== {name} ===")
        try:
            rc |= FETCHERS[name](args.dry_run, args.check, args.dest)
            if (args.build_index and not args.dry_run and not args.check) or (
                args.check and args.build_index
            ):
                build_index(name)
        except Exception as exc:  # noqa: BLE001
            log(f"  !! BŁĄD {name}: {exc}")
            rc |= 1
    log("\nGotowe.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
