# Robbo Obibok v2 — Build Plan

## Philosophy

v1 had 76 source files with 14 `entrypoint_*` modules, 10 `runtime_*` modules, and a `compatibility/` layer just to keep the old imports working. That's the DI framework talking, not the product.

v2 targets **~13 modules**, each earning its place. No module loaders, no export graphs, no binding assemblies, no facade re-exports. Composition via dataclasses and plain function calls.

---

## Target Architecture

```
src/robbo_obibok/
├── __init__.py           # Package marker
├── __main__.py           # python -m robbo_obibok
├── config.py             # YAML + env loading, validated dataclasses
├── models.py             # Track, Collection, PlaybackState
├── collections.py        # Collection registry, index loaders, metadata extraction
├── audio.py              # PulseAudio sink, Audacious lifecycle, volume/compressor
├── monitor.py            # Track completion detection (D-Bus + timeout)
├── queue.py              # Queue shuffle, blacklist, persistence
├── favorites.py          # Reaction-based favorites + named playlists
├── playback.py           # Orchestrator: play/skip/stop/auto-advance
├── bot.py                # discord.py Bot/Cog: commands + events
├── embeds.py             # Discord rich embed builders
├── persistence.py        # JSON file I/O (thin wrapper)
└── launcher.py           # Startup sequence, signal handling, graceful shutdown
```

**14 modules.** Each described below.

---

## Feature & Command Checklist

### Collections (7)

| ID | Format(s) | Tracks | Archive Path | Index File |
|----|-----------|--------|--------------|------------|
| `asma` | `.sap` | ~6,300 | `archiwum/asma/` | `asma_cache_local.json` |
| `hvsc` | `.sid` | ~60,500 | `archiwum/hvsc/C64Music/` | `hvsc_cache_local.json` |
| `ay` | `.ay` | ~4,500 | `archiwum/ay/` | `ay_cache_local.json` |
| `ym` | `.ym` | ~7,200 | `archiwum/ym/` | `ym_cache_local.json` |
| `modarchive` | `.mod` `.xm` `.s3m` `.it` | ~175,000 | `archiwum/modarchive/` | `modarchive_cache_local.json` |
| `tiny` | `.mod` `.xm` `.s3m` `.it` | ~550 | `archiwum/tiny/` | `tiny_cache_local.json` |
| `kgen` | `.mod` `.xm` `.s3m` `.it` | ~4,800 | `archiwum/kgen/` | `kgen_cache_local.json` |

### Metadata Extraction (per format)

| Format | Header Fields |
|--------|---------------|
| `.sap` (ASMA) | Author, Name, Copyright, Frames, Speed, Type |
| `.sid` (HVSC) | Name, Author, Copyright, SID version, Start page, Page size, Speed |
| `.ay` (ZX Spectrum) | Author, Name, Copyright |
| `.ym` (Atari ST) | Author, Name, Copyright |
| `.mod`/`.xm`/`.s3m`/`.it` | Title, Tracker, Sample names |

### Commands

| Command | Alias(es) | Description |
|---------|-----------|-------------|
| **Playback** | | |
| `!play` | `!pl` | Start shuffled radio from current collection |
| `!play <query>` | | Search and play first matching track |
| `!play <number>` | | Play track N from last search results |
| `!stop` | `!st` | Stop playback and disconnect |
| `!skip` | `!next` `!nt` | Skip to next track |
| `!jump <n>` | | Jump to track N in queue |
| `!np` | | Show current track info |
| `!queue` | `!q` | Show upcoming tracks |
| `!history` | | Show last 10 played tracks |
| `!sleep <min>` | | Stop playback after N minutes |
| `!loop` | | Toggle repeat current track |
| `!volume <0-200>` | | Set playback volume |
| `!clear` | | Clear the queue |
| **Collections** | | |
| `!flip` | `!switch` `!toggle` `!fl` | Rotate through all available collections |
| `!status` | `!mode` `!collection` | Show current collection and queue info |
| `!search <query>` | | Search tracks by name, directory, or author |
| `!hvsc` | `!c64` `!sid` | Switch to C64 SID |
| `!asma` | | Switch to Atari SAP |
| `!mod` | `!modarchive` `!modules` | Switch to ModArchive tracker modules |
| `!ay` | `!spectrum` `!zx` | Switch to ZX Spectrum AY |
| `!ym` | `!atarist` | Switch to Atari ST YM |
| `!tiny` | `!tm` | Switch to Tiny Music modules |
| `!kgen` | `!keygen` `!k` | Switch to Keygen Music |
| **Favorites & Blacklist** | | |
| `!favorites` | `!favs` | Show reaction-based favorites |
| `!favplay` | `!fp` | Play favorites in shuffle mode |
| `!favsave` | `!pls` | Save favorites as named playlist |
| `!favload` | `!fpl` | Load and play saved playlist |
| `!playlists` | `!plist` | List all saved playlists |
| `!blk` | | Blacklist the currently playing track |
| `!blks` | | Show blacklist |
| `!blkrm <n>` | | Remove track N from blacklist |
| **Tools** | | |
| `!stats` | | Show radio stats (uptime, tracks played) |
| `!export` | | Export queue as plain text |
| `!refresh` | | Re-crawl ASMA collection *(mods only)* |
| `!reindex` | | Re-fetch metadata from files *(mods only)* |

### Features

| Feature | Module | Notes |
|---------|--------|-------|
| Shuffle loop | `queue.py` | Never same track twice in a row |
| Rich metadata | `collections.py` + `embeds.py` | Track name, author, copyright from headers |
| Favorites | `favorites.py` | React to Now Playing embed → toggle save/remove |
| Named playlists | `favorites.py` | `!favsave` / `!favload` with named playlists |
| Blacklist | `queue.py` | `!blk` removes track from future queues |
| Auto-advance | `monitor.py` + `playback.py` | Next track when current ends (D-Bus monitoring) |
| GME-aware timeout | `monitor.py` | 600s timeout for GME/OpenMPT formats |
| Queue persistence | `queue.py` + `persistence.py` | Saves/restores queue across restarts |
| Auto-start | `bot.py` | Starts when someone joins configured voice channel |
| Auto-stop | `monitor.py` | Disconnects after channel empty for N seconds |
| Watchdog | `launcher.py` | Auto-restart Audacious if it crashes |
| Compressor | `audio.py` | Auto-enable at startup for loudness consistency |
| Per-collection volume | `audio.py` | HVSC=120%, others=100% |
| Search | `bot.py` + `collections.py` | `!search <query>` across name/directory/author |
| Export | `bot.py` | `!export` queue as plain text |
| Guild restriction | `config.py` | Optional single-server mode via `guild_id` |
| Process lock | `launcher.py` | PID file prevents duplicate instances |
| Graceful shutdown | `launcher.py` | SIGINT/SIGTERM → cleanup audio + save state |

### Audio Pipeline

```
File on disk
  → Audacious (headless, D-Bus control via audtool)
    → PulseAudio null-sink (asma_bot)
      → discord.py voice_client.play() (PCM stream)
        → Discord voice channel
```

| Component | Control |
|-----------|---------|
| PulseAudio sink | `pactl load-module module-null-sink` |
| Audacious | `subprocess.Popen(["audacious", "--headless"])` |
| Playback | `audtool playfile <path>` |
| Stop | `audtool stop` |
| Volume | `pactl set-sink-volume <sink> <percent>` |
| Track end | `audtool song` polling + output length check |
| Compressor | `audtool plugin-is-enabled compressor` |

---

## Module Responsibilities

### `config.py` — Configuration
- Load `config.yaml` with PyYAML
- Override with `DISCORD_BOT_TOKEN` env var
- Validated `@dataclass(slots=True)` containers: `AppConfig`, `AudioConfig`, `PlaybackConfig`, `ArchiveConfig`
- `derive_paths(root_dir, config)` → resolves all filesystem paths from config
- Pure synchronous module, no imports from other project modules

### `models.py` — Core Domain Types
- `Track(filepath, title, author, copyright, collection_id, file_ext)`
- `Collection(name, id, extensions, archive_path, cache_file, volume, loader_fn)`
- `PlaybackState(current_track, queue, position, guild_id, voice_channel_id, is_looping, is_playing)`
- Pure dataclasses, no business logic, no imports from other project modules

### `collections.py` — Collection Registry & Loaders
- `COLLECTIONS: dict[str, Collection]` — registry of all 7 collections
- `load_index(collection_id) -> list[Track]` — reads `*_cache_local.json`, returns track list
- `extract_metadata(filepath, format) -> dict[str, str]` — dispatches to format-specific parsers
- Format-specific metadata parsers: `_parse_sap_header()`, `_parse_sid_header()`, `_parse_mod_info()`, etc.
- `flip_collection(current_id) -> str` — rotate to next collection
- Imports: `config`, `models`, `persistence`

### `audio.py` — Audio Pipeline
- `setup_sink(sink_name)` — create PulseAudio null-sink via `pactl`
- `start_player()` — launch Audacious headless
- `stop_player()` — kill Audacious
- `play_file(filepath)` — tell Audacious to play a file via `audtool`
- `stop_playback()` — stop current track
- `set_volume(percent)` — `pactl set-sink-volume`
- `enable_compressor()` — auto-enable compressor plugin
- `ensure_audacious()` — health check + restart if needed
- Imports: `config`

### `monitor.py` — Track Completion
- `TrackMonitor` class — polls `audtool` D-Bus, detects track end
- `monitor_loop(state, on_track_end, on_empty_channel)` — async loop
- Per-collection timeout calculation (GME formats: 600s, others from songlengths)
- Disconnect on empty channel detection
- Imports: `audio`, `models`

### `queue.py` — Queue Management
- `shuffle_queue(tracks, state) -> list[Track]`
- `save_queue(state, guild_id, queue_dir)` — persist to JSON
- `load_queue(guild_id, queue_dir) -> PlaybackState | None` — restore from JSON
- `blacklist_track(state, filepath)` / `is_blacklisted(filepath)`
- Imports: `models`, `persistence`

### `favorites.py` — Favorites System
- `toggle_favorite(user_id, track, favorites_file)` — react-based add/remove
- `get_favorites(user_id, favorites_file) -> list[Track]`
- `save_playlist(name, tracks, user_id, playlist_dir)`
- `load_playlist(name, playlist_dir) -> list[Track]`
- Imports: `models`, `persistence`

### `playback.py` — Playback Orchestrator
- Central coordination module — ties together audio, queue, monitor, collections
- `play_track(ctx, state, track)` — full pipeline: stop current → load metadata → play → send embed → start monitor
- `skip_track(ctx, state)` — advance to next
- `stop_playback(ctx, state)` — stop + disconnect
- `auto_advance(ctx, state)` — called by monitor when track ends
- `start_radio(ctx, state)` — shuffle collection → play first track
- Imports: `audio`, `monitor`, `queue`, `models`, `collections`, `embeds`, `bot`

### `bot.py` — Discord Bot
- `class ObibokBot(commands.Bot)` — subclass or Cog
- All `!play`, `!stop`, `!skip`, `!np`, `!queue`, `!flip`, `!search`, etc.
- Voice channel connect/disconnect
- `on_ready` — auto-start logic
- `on_voice_state_update` — empty channel detection
- Reaction handling for favorites
- Imports: `playback`, `collections`, `models`, `favorites`, `embeds`

### `embeds.py` — Rich Embeds
- `now_playing_embed(track, collection_name, position, total) -> discord.Embed`
- `queue_embed(queue, position, page) -> discord.Embed`
- `status_embed(state, collection_name) -> discord.Embed`
- `error_embed(message) -> discord.Embed`
- Imports: `models`, `discord`

### `persistence.py` — JSON I/O
- `load_json(filepath) -> dict | list | None`
- `save_json(filepath, data)`
- `ensure_dir(path)`
- Thin wrappers over `json` module with error handling
- No project imports (leaf module)

### `launcher.py` — Startup & Lifecycle
- `main()` — orchestrate: load config → setup audio → create bot → run
- Signal handling (SIGINT, SIGTERM) → graceful shutdown
- PID file management
- Process lock (prevent duplicate instances)
- Imports: `config`, `audio`, `bot`

---

## Build Phases

### Phase 1: Skeleton & Infrastructure ✅
**Files:** `pyproject.toml`, `Makefile`, `__init__.py`, `__main__.py`, `.gitignore`, `config.yaml`, `.env.example`, `run_bot.sh`
**Goal:** `make install` and `make test` work (even with 0 tests). `make lint` passes.
**Tests:** Smoke test that package imports.

### Phase 2: Config + Models + Persistence ✅
**Files:** `config.py`, `models.py`, `persistence.py`
**Goal:** Config loads from YAML, models are defined, JSON I/O works.
**Tests:** Config parsing with defaults and overrides. Model construction. JSON round-trip.

### Phase 3: Collections ✅
**Files:** `collections.py`, `scripts/build_*_index.py` (all 7)
**Goal:** Index loading for all 7 collections. Metadata extraction per format. Collection flipping.
**Tests:** Load sample index files. Metadata extraction for each format. Collection flip cycle.

### Phase 4: Audio Pipeline ✅
**Files:** `audio.py`
**Goal:** PulseAudio sink creation, Audacious lifecycle, playback control.
**Tests:** Unit tests with mocked subprocess. Integration test (opt-in).

### Phase 5: Queue + Favorites ✅
**Files:** `queue.py`, `favorites.py`
**Goal:** Shuffle, blacklist, persistence, reaction-based favorites, named playlists.
**Tests:** Queue shuffle doesn't repeat. Persistence round-trip. Favorite toggle. Playlist save/load.

### Phase 6: Playback + Monitor ✅
**Files:** `playback.py`, `monitor.py`
**Goal:** Full playback orchestration. Track end detection. Auto-advance. Empty channel disconnect.
**Tests:** Playback state transitions. Monitor timeout calculation. Auto-advance logic.

### Phase 7: Discord Bot + Embeds ✅
**Files:** `bot.py`, `embeds.py`
**Goal:** All commands registered. Voice connection. Event handlers. Rich embeds.
**Tests:** Command behavior (mocked bot). Embed formatting. Auto-start/stop logic.

### Phase 8: Launcher + Deployment ✅
**Files:** `launcher.py`, `deploy/*.service`, `scripts/install.sh`, `scripts/test_launchers.sh`
**Goal:** `python -m robbo_obibok` works. Systemd services. Launcher smoke tests.
**Tests:** Launcher smoke tests.

---

## Design Decisions

### No sub-packages
`collections/` is the only sub-package in v1. In v2, collections are a single `collections.py` module — the 7 format parsers are private functions, not separate files. If the file grows past ~400 lines, we can split into `collections/` later.

### No DI framework
v1 built `CoreEventDependencies` with 17+ callback fields, `PlaybackSessionDependencies` with 15+, `MonitorPolicyDependencies` with 17+. That's indirection masquerading as decoupling.

v2 uses **direct function calls**. Modules import what they need. Testability comes from:
- Pure functions in `queue.py`, `favorites.py`, `collections.py`
- Mockable subprocess calls in `audio.py`
- The `bot.py` receives `PlaybackEngine` (from `playback.py`) at construction time

### `PlaybackEngine` — single coordination point
```python
@dataclass(slots=True)
class PlaybackEngine:
    config: AppConfig
    audio: AudioController
    monitor: TrackMonitor
    queue_mgr: QueueManager
    collections: CollectionRegistry
    favorites: FavoritesManager

    async def play(self, ctx, query=None): ...
    async def skip(self, ctx): ...
    async def stop(self, ctx): ...
    # etc.
```

`bot.py` holds one `PlaybackEngine` instance. All commands delegate to it. No 17-field dependency bundles.

### Flat module graph
```
launcher → bot → playback → audio, monitor, queue, collections, favorites, embeds
                              ↓
                          persistence, models, config
```
No cycles. No runtime binding assemblies. No `__getattr__` module magic.

---

## Estimated Module Sizes

| Module | ~Lines | Reasoning |
|--------|--------|-----------|
| `config.py` | 150 | YAML loading + 4 dataclasses + path derivation |
| `models.py` | 60 | 3 dataclasses (Track, Collection, PlaybackState) |
| `collections.py` | 350 | Registry + 7 format parsers + index loading |
| `audio.py` | 200 | PulseAudio + Audacious + volume |
| `monitor.py` | 150 | D-Bus polling + timeout + empty channel |
| `queue.py` | 120 | Shuffle + blacklist + persistence calls |
| `favorites.py` | 100 | Toggle + playlists |
| `playback.py` | 250 | Orchestration logic |
| `bot.py` | 400 | All commands + events + Cog setup |
| `embeds.py` | 100 | 4-5 embed builders |
| `persistence.py` | 40 | Thin JSON wrappers |
| `launcher.py` | 80 | Startup + signals + PID |
| **Total** | **~2,000** | vs v1's ~6,000+ |

---

## What We're NOT Building

- ❌ `entrypoint_*` modules (14 files → 0)
- ❌ `runtime_*` modules (10 files → 0)
- ❌ `compatibility/` layer (facade re-exports)
- ❌ Module loader / export graph / binding assembly
- ❌ `__getattr__` module-level magic
- ❌ Separate `bot_dependencies.py`, `bot_events.py`, `bot_persistence.py`
- ❌ `session_runtime.py`, `stream_runtime.py`, `subsong_runtime.py`
- ❌ `playback_lease.py`, `playback_helpers.py`, `playback_handlers.py`, `playback_assets.py`
- ❌ Domain architecture boundary tests (not needed when there are no forbidden imports — the architecture is flat)
