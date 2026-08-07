#!/usr/bin/env python3
"""Party Legacy Grabber — perelki z przeszlosci: historyczne wyniki compo.

Ten sam silnik co party_music_grabber.py, ale wstecz w czasie: dla wybranych
wielkich party (Assembly, Revision, Evoke, ...) bierze top-N z kazdego compo
muzycznego ze WSZYSTKICH lat i sciaga natywne formaty do
archiwum/party/legacy/<platform>/.

Uzycie:
  python party_legacy_grabber.py --dry-run --max-parties 4
  python party_legacy_grabber.py --party-regex "Assembly" --top 3
  python party_legacy_grabber.py --since-year 2000
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from index_config import load_archive_root
from party_music_grabber import (
    SLEEP_BETWEEN,
    fetch_all_parties,
    fetch_party_detail,
    fetch_prod_detail,
    get_music_placements,
    process_production,
    rebuild_cache,
)

# Domyślne "wielkie" party (regex po nazwie). Wybierz wlasne przez --party-regex.
# Silly Venture — atarowe party z Polski (SE/WE, 2x w roku).
DEFAULT_PARTY_REGEX = (
    r"Assembly|Revision|The Gathering|Breakpoint|Evoke|Xenium|DiHalt|"
    r"Sommarhack|Lovebyte|Nova|MountainBytes|Stream|Datastorm|The Party|"
    r"Codex Alimentarius|Birdie|Outline|Silly Venture"
)


def select_legacy_parties(regex: str, since_year: int) -> list[dict]:
    """Paginuj wszystkie party, zwroc pasujace do regex + rok >= since_year."""
    pattern = re.compile(regex, re.IGNORECASE)
    all_parties = fetch_all_parties(f"{since_year}-01-01")
    return [p for p in all_parties if pattern.search(p.get("name") or "")]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Party Legacy Grabber (historyczne compo -> archiwum)."
    )
    ap.add_argument("--party-regex", default=DEFAULT_PARTY_REGEX, help="regex nazw party")
    ap.add_argument("--top", type=int, default=3, help="ile top wynikow z compo (domyslnie 3)")
    ap.add_argument("--since-year", type=int, default=1985, help="od ktorego roku (domyslnie 1985)")
    ap.add_argument("--max-parties", type=int, default=0, help="limit party (0 = wszystkie)")
    ap.add_argument("--dry-run", action="store_true", help="tylko plan, bez pobierania")
    ap.add_argument("--no-cache-rebuild", action="store_true", help="nie przebudowuj cache")
    args = ap.parse_args()

    root_dir = Path(__file__).resolve().parent.parent
    party_root = load_archive_root(root_dir) / "party"
    cache_path = root_dir / "party_cache_local.json"

    print(
        f"== Party Legacy Grabber | party: {args.party_regex!r} | top={args.top} | od {args.since_year} =="
    )
    parties = select_legacy_parties(args.party_regex, args.since_year)
    parties.sort(key=lambda p: p.get("end_date") or "", reverse=True)
    if args.max_parties > 0:
        parties = parties[: args.max_parties]
    print(f"      -> {len(parties)} party (najnowsze pierwsze)")
    if not parties:
        print("Brak party — sprawdz regex.")
        return 0

    downloaded = skipped = 0
    for p in parties:
        pid = p["id"]
        pname = p.get("name", "?")
        pdate = (p.get("end_date") or "?")[:10]
        print(f"\n— {pname} (id={pid}, {pdate})")
        detail = fetch_party_detail(pid)
        if not detail:
            print("  (brak szczegolow)")
            continue
        placements = get_music_placements(detail, args.top)
        if not placements:
            print("  (brak compo muzycznych)")
            continue
        for compo, placement, prod in placements:
            print(f"  [{compo}] {placement}. {prod.get('title')!r} (id={prod.get('id')})")
            pdetail = fetch_prod_detail(prod["id"])
            if not pdetail:
                print("    (brak szczegolow produkcji)")
                continue
            ok, sk = process_production(
                pdetail, compo, placement, pname, party_root, args.dry_run, legacy=True
            )
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
