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
import ipaddress
import json
import os
import re
import shutil
import socket
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

from index_config import is_track_file, load_archive_root

DEMOZOO_UA = "curl/8.5.0"  # UA, ktory przechodzi przez Cloudflare na demozoo.org
DEMOZOO_API = "https://demozoo.org/api/v1"
SCENE_ORG = "files.scene.org"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 500
MAX_ARCHIVE_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024
MAX_REDIRECTS = 5

# Zaufane serwery plikow demosceny, ktore nie maja HTTPS (grabber pobiera z
# nich od poczatku; walidacja URL-i ma blokowac SSRF, nie lamac dzialajacych
# zrodel). scene.org traktujemy osobno przez _is_scene_org (prefix match).
TRUSTED_HTTP_HOSTS = {
    "sndh.atari.org",
    "events.retroscene.org",
    "files.dhs.nu",
    "no-fragments.atari.org",
    "dma-sc.atari.org",
    "csdb.dk",
    "ftp.pigwa.net",
    "iki.fi",
    "juicycube.net",
    "theparty.dk",
    "blog.argasinski.eu",
    "wavetable.cymru",
    "www.razor1911.com",
}

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
    "snd",
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
    "snd": "atarist",
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


# AppleDouble (._*) — pliki metadanych macOS; magic 00 05 16 07 na początku.
def is_apple_double(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"\x00\x05\x16\x07"
    except OSError:
        return False


def _is_scene_org(host: str) -> bool:
    return host == "scene.org" or host.endswith(".scene.org")


def _is_trusted_http_host(host: str) -> bool:
    return _is_scene_org(host) or host in TRUSTED_HTTP_HOSTS


def _validate_download_url(url: str) -> None:
    """Reject non-public download URLs before urllib opens a connection."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname
    if not host or parsed.username or parsed.password:
        raise ValueError("URL without a valid host")
    scheme = parsed.scheme.lower()
    if scheme != "https" and not (scheme == "http" and _is_trusted_http_host(host.lower())):
        raise ValueError("only HTTPS URLs are allowed (HTTP only for trusted hosts)")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"cannot resolve host {host}") from exc
    if not addresses:
        raise ValueError(f"cannot resolve host {host}")
    for _family, _type, _proto, _canonname, sockaddr in addresses:
        if not ipaddress.ip_address(sockaddr[0]).is_global:
            raise ValueError(f"non-public host {host}")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Return redirects to the caller so every hop is checked before opening."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_checked_url(url: str, timeout: int):
    """Open a URL after validating every redirect target (maximum five hops)."""
    opener = urllib.request.build_opener(_NoRedirectHandler())
    current_url = url
    for redirect in range(MAX_REDIRECTS + 1):
        _validate_download_url(current_url)
        req = urllib.request.Request(current_url, headers={"User-Agent": DEMOZOO_UA})
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location")
            if not location:
                raise IOError("redirect without Location header") from exc
            exc.close()
            if redirect == MAX_REDIRECTS:
                raise IOError(f"too many redirects (>{MAX_REDIRECTS})")
            current_url = urllib.parse.urljoin(current_url, location)
    raise AssertionError("unreachable")


def _download(url: str, dest: Path, retries: int = 3) -> bool:
    """Pobierz plik do dest (atomic). Zwraca True gdy OK."""
    # modlandowe URL bywaja z surowymi spacjami — urllib ich nie znosi
    url = _quote_url(url)
    for attempt in range(retries):
        tmp: str | None = None
        try:
            with _open_checked_url(url, timeout=90) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                    raise IOError("response exceeds 200 MB limit")
                dest.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
                size = 0
                with os.fdopen(fd, "wb") as fh:
                    while chunk := resp.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise IOError("response exceeds 200 MB limit")
                        fh.write(chunk)
            if not size:
                raise IOError("empty response")
            os.replace(tmp, dest)
            tmp = None
            return True
        except Exception as exc:
            if attempt == retries - 1:
                print(f"    ✗ download failed: {exc}")
            time.sleep(2 * (attempt + 1))
        finally:
            if tmp:
                Path(tmp).unlink(missing_ok=True)
    return False


def _quote_url(url: str) -> str:
    """Zakoduj spacje (i inne niebezpieczne znaki) w sciezce URL."""
    try:
        parsed = urllib.parse.urlsplit(url)
        path = urllib.parse.quote(parsed.path, safe="/%:@")
        return urllib.parse.urlunsplit(parsed._replace(path=path))
    except ValueError:
        return url


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
        if not isinstance(d, dict):
            print("  [err] invalid party list response", file=sys.stderr)
            break
        results = d.get("results", [])
        if not isinstance(results, list):
            print("  [err] invalid party list results", file=sys.stderr)
            break
        parties.extend(p for p in results if isinstance(p, dict))
        if not d.get("next"):
            break
        page += 1
        if page % 20 == 0:
            print(f"  ...strona {page}", file=sys.stderr)
        time.sleep(SLEEP_BETWEEN)
    today_iso = time.strftime("%Y-%m-%d")
    return [
        p
        for p in parties
        if isinstance(p.get("end_date"), str) and cutoff_iso <= p["end_date"][:10] <= today_iso
    ]


def fetch_party_detail(party_id: int) -> dict | None:
    return _get_json(f"{DEMOZOO_API}/parties/{party_id}/?format=json")


def fetch_prod_detail(prod_id: int) -> dict | None:
    return _get_json(f"{DEMOZOO_API}/productions/{prod_id}/?format=json")


def is_music_compo(name: str) -> bool:
    return bool(MUSIC_COMPO_RE.search((name or "").lower()))


def get_music_placements(party_detail: dict, top: int) -> list[tuple[str, int, dict]]:
    """Zwroc [(compo_name, placement, production_ref)] dla compo muzycznych."""
    out: list[tuple[str, int, dict]] = []
    competitions = party_detail.get("competitions", [])
    if not isinstance(competitions, list):
        return out
    for compo in competitions:
        if not isinstance(compo, dict):
            continue
        name = compo.get("name", "")
        if not isinstance(name, str):
            continue
        if not is_music_compo(name):
            continue
        results = compo.get("results", [])
        if not isinstance(results, list):
            continue
        for placement, res in enumerate(results[:top], start=1):
            if not isinstance(res, dict):
                continue
            prod = res.get("production") or {}
            if isinstance(prod, dict) and isinstance(prod.get("id"), int):
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
        lowered = {p.lower(): p for p in platforms if isinstance(p, str)}
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
    raw_platforms = prod.get("platforms", [])
    platforms = (
        [
            p.get("name")
            for p in raw_platforms
            if isinstance(p, dict) and isinstance(p.get("name"), str)
        ]
        if isinstance(raw_platforms, list)
        else []
    )
    sub = platform_dir(platforms)
    if not sub:
        sub = EXT_DIR.get(ext, "other")
    title = sanitize(prod.get("title") or Path(filename).stem)
    return sub, f"{title}.{ext}"


# ------------------------------------------------------------- Archiwa ---


def _is_safe_archive_member(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return bool(name) and not name.startswith(("/", "\\")) and ".." not in parts


def _validate_archive_members(members: list[tuple[str, int]]) -> bool:
    if len(members) > MAX_ARCHIVE_MEMBERS:
        print(f"    ! archiwum ma za dużo plików ({len(members)} > {MAX_ARCHIVE_MEMBERS})")
        return False
    total_size = sum(size for _name, size in members)
    if total_size > MAX_ARCHIVE_UNPACKED_BYTES:
        print("    ! archiwum przekracza limit 2 GB po rozpakowaniu")
        return False
    if any(size < 0 or not _is_safe_archive_member(name) for name, size in members):
        print("    ! archiwum zawiera podejrzaną ścieżkę")
        return False
    return True


def _list_7z_members(path: Path) -> list[tuple[str, int]] | None:
    """Return regular member names and unpacked sizes reported by 7z."""
    try:
        res = subprocess.run(
            ["7z", "l", "-slt", str(path)], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"    ! nie można sprawdzić archiwum: {exc}")
        return None
    if res.returncode:
        return None
    members: list[tuple[str, int]] = []
    for block in res.stdout.split("\n\n"):
        values = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        attributes = values.get("Attributes", "")
        if not attributes.startswith("D") and "Path" in values and "Size" in values:
            try:
                members.append((values["Path"], int(values["Size"])))
            except ValueError:
                return None
    return members


def unpack_archive(path: Path, dest_dir: Path) -> bool:
    """Rozpakuj zip/tar/7z/rar/lha do dest_dir. True gdy cos wyciagnieto."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    low = path.name.lower()
    try:
        if low.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                members = [
                    (info.filename, info.file_size) for info in z.infolist() if not info.is_dir()
                ]
                if not _validate_archive_members(members):
                    return False
                z.extractall(dest_dir)
            return True
        if (
            low.endswith(".tar")
            or low.endswith(".tgz")
            or low.endswith(".tar.gz")
            or low.endswith(".gz")
        ):
            with tarfile.open(path) as t:
                members = [
                    (member.name, member.size) for member in t.getmembers() if member.isfile()
                ]
                if not _validate_archive_members(members):
                    return False
                t.extractall(dest_dir, filter="data")
            return True
        # 7z / rar / lha / lzh przez binarke 7z (bezpieczny sandbox: -o dest)
        if low.endswith((".7z", ".rar", ".lha", ".lzh")):
            members = _list_7z_members(path)
            if members is None or not _validate_archive_members(members):
                return False
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


def copy_deduped(source: Path, dest: Path) -> Path:
    """Copy without overwriting a concurrent grabber's file."""
    size = source.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(100):
        target = dedupe_path(dest, size)
        if target == Path():
            return target
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".part")
        os.close(fd)
        try:
            shutil.copy2(source, tmp)
            try:
                os.link(tmp, target)
            except FileExistsError:
                continue
            return target
        finally:
            Path(tmp).unlink(missing_ok=True)
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
    links = prod.get("download_links", []) if isinstance(prod, dict) else []
    if not isinstance(links, list) or not links:
        title = prod.get("title") if isinstance(prod, dict) else None
        print(f"    {placement}. {title!r} — brak linków (pomijam)")
        return 0, 1
    ok = skip = 0
    for link in links:
        try:
            if not isinstance(link, dict):
                raise ValueError("nieprawidłowy wpis linku")
            url = link.get("url", "").strip()
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
            _validate_download_url(_quote_url(url))
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
                                candidate = Path(root) / f
                                if is_track_file(candidate, ACCEPTED_EXTS):
                                    candidates.append(candidate)
                    else:
                        print("      ! archiwum nierozpakowane")
                for cand in candidates:
                    if not is_track_file(cand, ACCEPTED_EXTS) or is_apple_double(cand):
                        print(f"      ~ {cand.name} — niegrywalny lub AppleDouble (pomijam)")
                        continue
                    cls = classify(prod, cand.name)
                    if not cls:
                        continue
                    sub, fname_out = cls
                    target = copy_deduped(cand, base / sub / fname_out)
                    if target == Path():
                        print(f"      = {prefix}{sub}/{fname_out} (duplikat)")
                        skip += 1
                        continue
                    print(f"      ✓ {prefix}{sub}/{target.name}")
                    ok += 1
        except Exception as exc:
            print(f"      ! link pominięty: {exc}")
            skip += 1
            continue
    return ok, skip


def rebuild_cache(party_root: Path, cache_path: Path) -> None:
    entries: list[dict] = []
    for root, _dirs, files in os.walk(party_root):
        for f in sorted(files):
            full = Path(root) / f
            if is_track_file(full, ACCEPTED_EXTS):
                rel = str(full.relative_to(party_root.parent))
                entries.append({"path": rel, "name": Path(f).stem, "size": os.path.getsize(full)})
    cache = {"version": 1, "total": len(entries), "tracks": entries}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(cache_path.parent), prefix=f".{cache_path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, cache_path)
    finally:
        Path(tmp).unlink(missing_ok=True)
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
    party_root = args.party_dir or (load_archive_root(root_dir) / "party")
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
        pid = p.get("id")
        if not isinstance(pid, int):
            print("  (nieprawidłowy wpis party)")
            continue
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
            try:
                prod_id = prod.get("id")
                if not isinstance(prod_id, int):
                    raise ValueError("nieprawidłowe id produkcji")
                print(f"  [{compo}] {placement}. {prod.get('title')!r} (id={prod_id})")
                pdetail = fetch_prod_detail(prod_id)
                if not isinstance(pdetail, dict):
                    print("    (brak szczegółów produkcji)")
                    continue
                ok, sk = process_production(
                    pdetail, compo, placement, pname, party_root, args.dry_run
                )
                downloaded += ok
                skipped += sk
            except Exception as exc:
                print(f"    ! produkcja pominięta: {exc}")
                skipped += 1
            time.sleep(SLEEP_BETWEEN)

    print(
        f"\n== Wynik: {downloaded} plików {'w planie' if args.dry_run else 'pobranych'}, {skipped} pominiętych =="
    )
    if not args.dry_run and not args.no_cache_rebuild:
        rebuild_cache(party_root, cache_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
