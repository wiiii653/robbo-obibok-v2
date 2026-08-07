#!/usr/bin/env python3
"""Party Music Grabber — comiesieczny zbieracz muzyki z party demoscenowych.

Zrodlo: Demozoo API (primary). Pouet pozostaje fallbackiem na przyszlosc —
API Poueta nie wystawia wygodnie wynikow party (stan na 2026-08).

Plan dzialania:
  1. Pobierz liste party z okna czasowego (domyslnie 45 dni wstecz).
  2. Dla kazdego party pobierz szczegoly (kompetitions) i wybierz muzyczne.
  3. Z kazdego compo wez top-N wynikow (placement 1..N).
  4. Dla kazdej produkcji pobierz szczegoly (platformy + download_links).
  5. Pobierz pliki (scene.org /view/ -> /get/, archiwa, bezposrednie linki).
  6. Rozpakuj archiwa, sklasyfikuj po platformie/rozszerzeniu, wrzuc do
     archiwum/party/<platform>/ (dedupe po nazwie+rozmiarze, atomic writes).
  7. Przebuduj party_cache_local.json (format: {path, name, size}).

Uzycie:
  python party_music_grabber.py --dry-run             # odkrycie + plan
  python party_music_grabber.py                       # pelny przebieg
  python party_music_grabber.py --window-days 60 --top 3
  python party_music_grabber.py --no-cache-rebuild    # bez przebudowy cache

Exit code: 0 = OK (nawet gdy nic nowego), 1 = blad krytyczny.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

DEMOZOO_UA = "curl/8.5.0"  # UA, ktory przechodzi przez Cloudflare na demozoo.org
DEMOZOO_API = "https://demozoo.org/api/v1"
SCENE_ORG = "files.scene.org"

# Natywne formaty platform, ktore Robbo umie zagrac (kolekcje + GME console
# plugin). BEZ nagran (mp3/wav/ogg) — tylko wlasciwe formaty maszyn:
#   sid (C64), sap (Atari 8-bit), ay (ZX), ym (Atari ST), nsf (NES),
#   vgm/vgz (Mega Drive), mod/xm/it/s3m/med/dmf (trackery Amiga/PC).
# monitor.py: CONSOLE_EXTENSIONS = {nsf, sap, vgm, vgz, sid, ay, ym} — dla
# tych formatow timeout jest wall-clockowy; trackery (mod/xm/it/s3m) wykrywaja
# koniec przez output-length drop.
ACCEPTED_EXTS = {
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
    "sndh",
}

# Katalog docelowy wg platformy z Demozoo (nazwa -> katalog, case-insensitive).
PLATFORM_DIR = {
    "Commodore 64": "c64",
    "Atari 8-bit": "atari8",
    "Atari 2600": "atari2600",
    "ZX Spectrum": "zx",
    "Atari ST": "atarist",
    "Amiga": "amiga",
    "Amiga (OCS/ECS)": "amiga",
    "Amiga AGA": "amiga",
    "PC": "pc",
    "MS-DOS": "pc",
    "MS-Dos": "pc",
    "Windows": "pc",
    "Linux": "pc",
    "Nintendo Entertainment System (NES)": "nes",
    "NES": "nes",
    "Mega Drive": "megadrive",
    "Sega Mega Drive": "megadrive",
    "Amstrad CPC": "amstrad_cpc",
}

# Fallback po rozszerzeniu, gdy platforma nieznana.
EXT_DIR = {
    "sid": "c64",
    "sap": "atari8",
    "sndh": "atarist",
    "ay": "zx",
    "ym": "atarist",
    "nsf": "nes",
    "vgm": "megadrive",
    "vgz": "megadrive",
    "mod": "amiga",
    "med": "amiga",
    "okt": "amiga",
    "xm": "pc",
    "it": "pc",
    "s3m": "pc",
    "dmf": "pc",
}

# Archiwa do rozpakowania.
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".lha", ".lzh", ".tar", ".gz", ".tgz", ".tar.gz"}

# Compa muzyczne: nazwa compo pasuje do tych wzorcow (lowercase).
MUSIC_COMPO_RE = re.compile(
    r"music|chiptune|chip.?tunes|tracked|tracker|symphony|fast.?music|listening|dance.?music"
)

SLEEP_BETWEEN = 0.4  # sekundy miedzy zadaniami API (rate limit)


# ---------------------------------------------------------------- HTTP ---


def _get_json(url: str, retries: int = 6) -> dict | None:
    """GET z retry/backoff. Zwraca dict lub None po wyczerpaniu prob."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": DEMOZOO_UA})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(3 + attempt * 3)
                continue
            print(f"  [http {exc.code}] {url}", file=sys.stderr)
            return None
        except Exception as exc:
            time.sleep(2 + attempt * 2)
            if attempt == retries - 1:
                print(f"  [err] {url}: {exc}", file=sys.stderr)
    return None


def _download(url: str, dest: Path, retries: int = 3) -> bool:
    """Pobierz plik do dest (atomic). Zwraca True gdy OK."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": DEMOZOO_UA})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            if not data:
                raise IOError("empty response")
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)
            return True
        except Exception as exc:
            if attempt == retries - 1:
                print(f"    ✗ download failed: {exc}")
            time.sleep(2 * (attempt + 1))
    return False


# ------------------------------------------------------------- Demozoo ---


def fetch_all_parties(cutoff_iso: str) -> list[dict]:
    """Paginate po wszystkich party, zwroc te z cutoff <= end_date <= dzisiaj."""
    parties: list[dict] = []
    page = 1
    while True:
        url = f"{DEMOZOO_API}/parties/?format=json&page_size=100&page={page}"
        d = _get_json(url)
        if not d:
            break
        parties.extend(d.get("results", []))
        if not d.get("next"):
            break
        page += 1
        if page % 20 == 0:
            print(f"  ...strona {page}", file=sys.stderr)
        time.sleep(SLEEP_BETWEEN)
    today_iso = time.strftime("%Y-%m-%d")
    return [p for p in parties if cutoff_iso <= (p.get("end_date") or "")[:10] <= today_iso]


def fetch_party_detail(party_id: int) -> dict | None:
    return _get_json(f"{DEMOZOO_API}/parties/{party_id}/?format=json")


def fetch_prod_detail(prod_id: int) -> dict | None:
    return _get_json(f"{DEMOZOO_API}/productions/{prod_id}/?format=json")


def is_music_compo(name: str) -> bool:
    return bool(MUSIC_COMPO_RE.search((name or "").lower()))


def get_music_placements(party_detail: dict, top: int) -> list[tuple[str, int, dict]]:
    """Zwroc [(compo_name, placement, production_ref)] dla compo muzycznych."""
    out: list[tuple[str, int, dict]] = []
    for compo in party_detail.get("competitions", []):
        name = compo.get("name", "")
        if not is_music_compo(name):
            continue
        for placement, res in enumerate(compo.get("results", [])[:top], start=1):
            prod = res.get("production") or {}
            if prod.get("id"):
                out.append((name, placement, prod))
    return out


# --------------------------------------------------------- Klasyfikacja ---


def sanitize(name: str, max_len: int = 80) -> str:
    """Bezpieczna nazwa pliku: litery/cyfry/spacje/myślniki, przycieta."""
    s = re.sub(r"[^\w\s\-\.]+", "", name, flags=re.UNICODE).strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return s[:max_len] or "untitled"


def platform_dir(platforms: list[str]) -> str | None:
    if platforms:
        lowered = {p.lower(): p for p in platforms}
        for key, d in PLATFORM_DIR.items():
            if key.lower() in lowered:
                return d
        # nieznana platforma -> zsanitizowana nazwa jako katalog
        return sanitize(platforms[0], 24).lower().replace(" ", "_") or None
    return None


def classify(prod: dict, filename: str) -> tuple[str, str] | None:
    """Zwroc (podkatalog, docelowa_nazwa) albo None (plik niegrywalny)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ACCEPTED_EXTS:
        return None
    platforms = [p.get("name") for p in prod.get("platforms", [])]
    sub = platform_dir(platforms)
    if not sub:
        sub = EXT_DIR.get(ext, "other")
    title = sanitize(prod.get("title") or Path(filename).stem)
    return sub, f"{title}.{ext}"


# ------------------------------------------------------------- Archiwa ---


def unpack_archive(path: Path, dest_dir: Path) -> bool:
    """Rozpakuj zip/tar/7z/rar/lha do dest_dir. True gdy cos wyciagnieto."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    low = path.name.lower()
    try:
        if low.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                z.extractall(dest_dir)
            return True
        if (
            low.endswith(".tar")
            or low.endswith(".tgz")
            or low.endswith(".tar.gz")
            or low.endswith(".gz")
        ):
            with tarfile.open(path) as t:
                t.extractall(dest_dir, filter="data")
            return True
        # 7z / rar / lha / lzh przez binarke 7z (bezpieczny sandbox: -o dest)
        if low.endswith((".7z", ".rar", ".lha", ".lzh")):
            res = subprocess.run(
                ["7z", "x", "-y", f"-o{dest_dir}", str(path)],
                capture_output=True,
                timeout=180,
            )
            return res.returncode == 0
    except Exception as exc:
        print(f"    ! rozpakowanie nieudane: {exc}")
    return False


# ---------------------------------------------------------------- Run ---


def dedupe_path(dest: Path, size: int) -> Path:
    """Jesli plik o tej nazwie juz jest (ta sama wielkosc) -> skip (None).
    Inny rozmiar -> dopisz ' (2)', ' (3)'..."""
    if not dest.exists():
        return dest
    if dest.stat().st_size == size:
        return Path()  # marker: duplikat (ta sama zawartosc)
    stem, ext = dest.stem, dest.suffix
    for i in range(2, 100):
        cand = dest.with_name(f"{stem} ({i}){ext}")
        if not cand.exists():
            return cand
    return Path()


def process_production(
    prod: dict,
    compo: str,
    placement: int,
    party_name: str,
    party_root: Path,
    dry: bool,
    *,
    legacy: bool = False,
) -> tuple[int, int]:
    """Pobiera/planuje pliki produkcji. Zwraca (pobrane, pominiete)."""
    base = party_root / "legacy" if legacy else party_root
    prefix = "legacy/" if legacy else ""
    links = prod.get("download_links", [])
    if not links:
        print(f"    {placement}. {prod.get('title')!r} — brak linków (pomijam)")
        return 0, 1
    ok = skip = 0
    for link in links:
        url = (link.get("url") or "").strip()
        if not url:
            continue
        # scene.org /view/ -> /get/ (bezposredni download)
        if SCENE_ORG in url and "/view/" in url:
            url = url.replace("/view/", "/get/", 1)
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        fname = Path(path).name or "download.bin"
        # scene.org download.php?file=... — wyciagnij prawdziwy plik z query
        if fname.lower() == "download.php" and parsed.query:
            q = urllib.parse.parse_qs(parsed.query)
            if q.get("file"):
                fname = Path(q["file"][0]).name or fname
                url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urllib.parse.urlencode({'file': q['file'][0]})}"
        ext = Path(fname).suffix.lower().lstrip(".")
        if ext not in ACCEPTED_EXTS and f".{ext}" not in ARCHIVE_EXTS:
            print(f"      ~ {fname} — nie-muzyczny (pomijam link)")
            continue
        if dry:
            print(f"      [plan] {url}")
            ok += 1
            continue
        # pobierz do tymczasowego katalogu
        with tempfile.TemporaryDirectory(prefix="party_") as tmp:
            tmp_dir = Path(tmp)
            raw = tmp_dir / fname
            print(f"      ↓ {fname} ({url})")
            if not _download(url, raw):
                skip += 1
                continue
            candidates: list[Path] = [raw] if ext in ACCEPTED_EXTS else []
            if f".{ext}" in ARCHIVE_EXTS:
                extract_dir = tmp_dir / "x"
                if unpack_archive(raw, extract_dir):
                    for root, _dirs, files in os.walk(extract_dir):
                        for f in files:
                            if Path(f).suffix.lower().lstrip(".") in ACCEPTED_EXTS:
                                candidates.append(Path(root) / f)
                else:
                    print("      ! archiwum nierozpakowane")
            for cand in candidates:
                cls = classify(prod, cand.name)
                if not cls:
                    continue
                sub, fname_out = cls
                target = dedupe_path(base / sub / fname_out, cand.stat().st_size)
                if target == Path():
                    print(f"      = {prefix}{sub}/{fname_out} (duplikat)")
                    skip += 1
                    continue
                if not dry:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cand, target)
                    print(f"      ✓ {prefix}{sub}/{target.name}")
                ok += 1
    return ok, skip


def rebuild_cache(party_root: Path, cache_path: Path) -> None:
    entries: list[dict] = []
    for root, _dirs, files in os.walk(party_root):
        for f in sorted(files):
            ext = Path(f).suffix.lower().lstrip(".")
            if ext in ACCEPTED_EXTS:
                full = Path(root) / f
                rel = str(full.relative_to(party_root.parent))
                entries.append({"path": rel, "name": Path(f).stem, "size": os.path.getsize(full)})
    cache = {"version": 1, "total": len(entries), "tracks": entries}
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")
    print(f"[cache] {len(entries)} tracków -> {cache_path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Party Music Grabber (Demozoo -> Robbo archive).")
    ap.add_argument(
        "--window-days", type=int, default=45, help="okno czasowe w dniach (domyslnie 45)"
    )
    ap.add_argument("--top", type=int, default=5, help="ile top wynikow z compo (domyslnie 5)")
    ap.add_argument("--dry-run", action="store_true", help="tylko odkryj i pokaz plan")
    ap.add_argument(
        "--no-cache-rebuild", action="store_true", help="nie przebudowuj cache na koncu"
    )
    ap.add_argument(
        "--party-dir", type=Path, help="katalog archiwum party (domyslnie archiwum/party)"
    )
    args = ap.parse_args()

    root_dir = Path(__file__).resolve().parent.parent
    # archiwum/ w repo to symlink do wlasciwego archiwum (config.yaml archive.path)
    party_root = args.party_dir or (root_dir / "archiwum" / "party")
    cache_path = root_dir / "party_cache_local.json"

    today = time.strftime("%Y-%m-%d")
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - args.window_days * 86400))
    print(f"== Party Music Grabber | okno: {cutoff}..{today} | top={args.top} ==")

    # 1. party
    print("[1/4] Pobieram listę party z Demozoo...")
    parties = fetch_all_parties(cutoff)
    parties.sort(key=lambda p: p.get("end_date") or "", reverse=True)
    print(f"      -> {len(parties)} party w oknie")
    if not parties:
        print("Brak party w oknie — nic do roboty.")
        return 0

    downloaded = skipped = 0
    for p in parties:
        pid = p["id"]
        pname = p.get("name", "?")
        print(f"\n— {pname} (id={pid}, {p.get('end_date')})")
        detail = fetch_party_detail(pid)
        if not detail:
            print("  (brak szczegółów)")
            continue
        placements = get_music_placements(detail, args.top)
        if not placements:
            print("  (brak compo muzycznych)")
            continue
        for compo, placement, prod in placements:
            print(f"  [{compo}] {placement}. {prod.get('title')!r} (id={prod.get('id')})")
            pdetail = fetch_prod_detail(prod["id"])
            if not pdetail:
                print("    (brak szczegółów produkcji)")
                continue
            ok, sk = process_production(pdetail, compo, placement, pname, party_root, args.dry_run)
            downloaded += ok
            skipped += sk
            time.sleep(SLEEP_BETWEEN)

    print(
        f"\n== Wynik: {downloaded} plików {'w planie' if args.dry_run else 'pobranych'}, {skipped} pominiętych =="
    )
    if not args.dry_run and not args.no_cache_rebuild:
        rebuild_cache(party_root, cache_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
