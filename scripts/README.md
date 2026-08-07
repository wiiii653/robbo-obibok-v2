# Robbo v2 — skrypty archiwów i indeksów

## Pobieranie archiwów — `fetch_archives.py`

Jeden downloader dla wszystkich kolekcji Robbo v2. Używa tylko stdlib (urllib)
+ `7z` (p7zip) do rozpakowywania. Źródła zweryfikowane 2026-08-05.

| Archiwum | Źródło | Rozmiar | Uwagi |
|---|---|---|---|
| **hvsc** (C64 SID) | API hvsc.c64.org (wersja) + mirror `hvsc.brona.dk` | pełne ~81 MB / update ~3.3 MB | oficjalny hosting XS4ALL padł — mirror serwuje pliki |
| **asma** (Atari SAP) | `asma.atari.org/asmadb/asma.zip` | ~20 MB | zip zawiera `asma/` — strip 1 poziomu |
| **ay** (ZX Spectrum AY) | `ay.strangled.net` — Tr_Songs.7z, bulba_ay.7z, ifist_ay.zip | ~26 MB | + YM.7z, VtxYmEtc.7z, faveym.7z |
| **ym** (Atari ST YM) | `ay.strangled.net` — YM_Archive_v5.7z, YM.7z, VtxYmEtc.7z, faveym.7z | ~6.5 MB | Modland YM pobierany osobno (FTP) |
| **kgen** (keygen music) | GitHub `6512345/keygenmusic` (codeload zip) | ~430 MB | strip 1 poziomu (root `keygenmusic-main/`) |
| **modarchive** | `modarchive.textfiles.com` snapshot | GB! | deleguje do `download_modarchive_bulk.py` |
| **tiny** (demoscene) | `scripts/fetch_pouet_mods.py` + `pouet_manifest.json` | ~165 MB | manifest 25 artystów (tłuściochy v2), 264 pliki |

### Użycie

```bash
# sprawdź stan (API, rozmiary, obecność lokalna) — nic nie pobiera
python3 fetch_archives.py all --check

# plan bez pobierania
python3 fetch_archives.py hvsc --dry-run

# pobierz i rozpakuj jedno archiwum
python3 fetch_archives.py hvsc

# wszystko (modarchive = GB!, ostrożnie)
python3 fetch_archives.py all

# po pobraniu przebuduj cache lokalny
python3 fetch_archives.py hvsc --build-index

# nadpisz katalog docelowy (np. test)
python3 fetch_archives.py asma --dest /tmp/test
```

### Jak działa HVSC

1. API `hvsc.c64.org/api/v1/version/7z` daje najnowszą wersję (np. 85).
2. Jeśli brak `C64Music/` → pobiera pełny `HVSC_<v>-all-of-them.7z` z mirrora.
3. Jeśli jest → pobiera `HVSC_Update_<v>.7z` i **wtapia** go: `update/new/*`
   kopiowane do właściwych katalogów, `update/fix/*` nadpisuje stare wersje.
4. Weryfikacja: newsy #85 deklarują 61 157 SID-ów — tyle dokładnie jest po
   pełnym pobraniu; update dodaje 630 plików (587 new + 43 fix).

### Pułapki wykryte w testach

- **Raw FTP ≠ URL**: ftplib wysyła surowe komendy — prawdziwe spacje, nie `%20`.
- **XS4ALL nie żyje**: `boswme.home.xs4all.nl` przekierowuje na `notxs4all`
  (strona o zamknięciu hostingu). Mirror: `hvsc.brona.dk` (ta sama struktura).
- **archive.org wymaga UA przeglądarki** (500 na `BorutaBot`).
- **GitHub codeload** nie wspiera HEAD Content-Length — rozmiar "nieznany".
- **HVSC update** nie jest archiwum z plikami na wierzchu — ma `update/new/`
  i `update/fix/`, które trzeba wtopić w C64Music.

## Party music — `party_music_grabber.py` / `party_legacy_grabber.py`

Comiesięczny grabber top-5 z compo muzycznych (Demozoo API, UA `curl/8.5.0` —
Firefox blokuje Cloudflare). Tylko **natywne formaty** (sid/sap/ay/ym/sndh +
trackery) — bez mp3/wav/ogg nagrań. Wrzutka do `archiwum/party/<platform>/`
i przebudowa `party_cache_local.json`.

```bash
# comiesięczny: wszystkie party z okna 45 dni (cron: 7. dnia miesiąca 06:00)
python3 party_music_grabber.py
# wstecz w czasie: wielkie party (Assembly|Silly Venture|...) cała historia
python3 party_legacy_grabber.py --top 3
# suchy przebieg / małe okno
python3 party_music_grabber.py --dry-run --window-days 12
```

Wyniki z 2026-08-07: legacy sweep zebrał **1212 plików** (1990–2026,
`archiwum/party/legacy/<platform>/`), comiesięczny 41 — kolekcja `!party`
ma **1270 tracków**.

Pułapki (załata 2026-08-07):
- **AppleDouble** (`._*` w `__MACOSX/` z zipów scene.org) — odsiewane 3
  warstwami: skip `._*`/dotfiles, skip `__MACOSX/`, magic `00 05 16 07`.
- **modland URL ze spacjami** — `_quote_url()` przed pobraniem.
- **martwe linki scene.org** — raportowane (`✗ download failed`) i pomijane.

Wrapper crona: `~/.hermes/scripts/party_music_grabber.sh` (TMPDIR na dysku).

## Budowanie indeksów — `build_*_index.py`

Skanują lokalne archiwa i piszą `*_cache_local.json` w formacie
`{"version":1,"total":N,"tracks":[{path,size,...}]}` konsumowanym przez
`_load_path_cache()`.

```bash
python3 build_asma_index.py        # asma_cache_local.json
python3 build_hvsc_index.py        # hvsc_cache_local.json
python3 build_ay_index.py          # ay_cache_local.json
python3 build_ym_index.py          # ym_cache_local.json
python3 build_kgen_index.py        # kgen_cache_local.json
python3 build_modarchive_index.py  # modarchive_cache_local.json
python3 build_tiny_index.py        # tiny_cache_local.json
python3 build_party_index.py       # party_cache_local.json
```

`index_config.py` — wspólny `load_archive_root()` (czyta `config.yaml` →
`archive.path`, domyślnie `archiwum/`).
