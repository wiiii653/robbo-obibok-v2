# AGENTS.md — Robbo Obibok v2

## Project Overview

Discord chiptune radio bot that streams vintage retro chipmusic from seven collections (ASMA, HVSC, AY, YM, ModArchive, Tiny Music, KGen). Users join a voice channel, type `!play`, and the bot streams shuffled tracks with metadata. Built with discord.py, Audacious (headless audio player), PulseAudio, and FFmpeg.

## Tech Stack

- **Language:** Python 3.11–3.13 (use `from __future__ import annotations` in every file)
- **Framework:** discord.py 2.3+ with voice support
- **Audio:** Audacious headless + PulseAudio null-sink + FFmpeg + sidplayfp
- **Package manager:** uv (lock files), pip for venv
- **Build:** setuptools via pyproject.toml
- **Linting:** ruff (line-length=100, select F/E/W/I, ignore E501)
- **Testing:** pytest + pytest-cov (coverage ≥ 65%)
- **No mypy** — type hints are used but mypy is not in the toolchain

## Architecture — Flat Module Layout

```
src/
├── __init__.py            # Package marker
├── __main__.py            # Entry point (python -m src)
├── config.py              # YAML/env configuration loading
├── models.py              # Data models and dataclasses
├── persistence.py         # JSON file read/write
├── collection_loader.py   # Collection index loading and catalog
├── audio.py               # Audio process management (Audacious, PulseAudio, FFmpeg)
├── queue.py               # Track queue per guild
├── favorites.py           # User favorites (react-to-save)
├── playback.py            # Playback session logic and commands
├── monitor.py             # Audio monitor (track completion detection)
├── embeds.py              # Discord embed builders (Now Playing, etc.)
├── bot.py                 # Discord bot client, events, command routing
└── launcher.py            # Bot startup and lifecycle management
```

## Project Structure

```
robbo-obibok-v2/
├── src/                        # Source package (flat layout)
│   ├── __init__.py             # Package marker
│   ├── __main__.py             # Entry point
│   ├── config.py               # Configuration loading
│   ├── models.py               # Data models and dataclasses
│   ├── persistence.py          # JSON file read/write
│   ├── collection_loader.py    # Collection index loading
│   ├── audio.py                # Audio process management
│   ├── queue.py                # Track queue per guild
│   ├── favorites.py            # User favorites
│   ├── playback.py             # Playback session logic
│   ├── monitor.py              # Audio monitor
│   ├── embeds.py               # Discord embed builders
│   ├── bot.py                  # Discord bot client
│   └── launcher.py             # Bot startup lifecycle
├── tests/
│   ├── integration/            # Real dependency tests (opt-in via env vars)
│   └── test_*.py               # Unit tests
├── scripts/
│   ├── build_*_index.py        # Local index builders
│   ├── install.sh              # Installation script
│   └── test_launchers.sh       # Launcher smoke tests
├── deploy/                     # systemd service files
├── docs/                       # Documentation
├── config.yaml                 # Runtime configuration
├── pyproject.toml              # Dependencies + tool config
├── Makefile                    # Build/test commands
├── run_bot.sh                  # Entrypoint wrapper
├── .env.example                # Token template
└── var/                        # Runtime data (queues, playlists, tmp, logs)
```

## Code Conventions

- `from __future__ import annotations` in every file
- Type hints everywhere — avoid `Any` where possible
- Async-first for all I/O operations
- `dataclasses(slots=True)` for data containers
- No `exec`/`eval`, no bare `except:`
- Double quotes for strings, space indentation (ruff format)
- Imports sorted with isort (ruff handles this)
- Test files can have relaxed import ordering (E402 suppressed)

## Key Commands

```bash
make install          # Full setup (venv + deps + indexes)
make run              # Start the bot
make run-strict       # Start in strict compat mode
make test             # Unit tests (excludes tests/integration)
make test-integration # Real dependency integration tests
make test-launchers   # Launcher smoke tests
make lint             # ruff check src/ tests/ scripts/
make format           # ruff format src/ tests/ scripts/
make build-indexes    # Build all local track indexes
make clean            # Remove venv, caches, temp files
```

## Configuration

- `config.yaml` — runtime config (command prefix, guild, audio, playback, auto-start/stop)
- `.env` — `DISCORD_BOT_TOKEN` (required)
- `DISCORD_BOT_TOKEN` env var overrides config.yaml token
- `ROBBO_STRICT_COMPAT=1` — enables strict compatibility mode
- `guild_id` — optional, restricts bot to single Discord server

## Collections

| ID       | Format        | Tracks  | Archive Path            |
|----------|---------------|---------|-------------------------|
| asma     | .sap          | ~6,300  | archiwum/asma/          |
| hvsc     | .sid          | ~60,500 | archiwum/hvsc/C64Music/ |
| ay       | .ay           | ~4,500  | archiwum/ay/            |
| ym       | .ym           | ~7,200  | archiwum/ym/            |
| modarchive| .mod/.xm/.s3m/.it | ~175,000 | archiwum/modarchive/ |
| tiny     | .mod/.xm/.s3m/.it | ~550    | archiwum/tiny/          |
| kgen     | .mod/.xm/.s3m/.it | ~4,800  | archiwum/kgen/          |

All archives served from local disk. Indexes are pre-built as `*_cache_local.json`.

## Audio Pipeline

1. PulseAudio null-sink (`asma_bot`) created via `pactl`
2. Audacious headless started, routes audio to the sink
3. Bot connects to Discord voice channel via `voice_client.play()`
4. Audio monitored via `audtool` D-Bus commands for track completion
5. Compressor plugin auto-enabled at startup for loudness consistency
6. Per-collection volume normalization (HVSC=120%, others=100%)

## Testing

- Unit tests: `make test` (offline, excludes `tests/integration`)
- Integration tests require env vars: `DISCORD_INTEGRATION_TOKEN`, `RUN_LIVE_AUDIO_INTEGRATION=1`, `RUN_LOCAL_ARCHIVE_INTEGRATION=1`
- Launcher smoke tests via `scripts/test_launchers.sh`

## Patterns to Follow

- **Dependency injection:** Use callback protocols and dataclass-based dependency bundles
- **Event-driven:** Discord events trigger callbacks through dependency bundles
- **Session context:** Each guild gets a `PlaybackSessionContext` with isolated state
- **Collection switching:** `CollectionSpec` dataclass defines load/flip/error messages per collection
- **Queue persistence:** JSON files in `var/queues/` per guild
- **Favorites:** React to Now Playing embeds, stored in `favorites.json`

## Deployment

- systemd user service files in `deploy/`
- Token stored in `~/robbo-obibok/.env` (chmod 600)
- PID file at project root (`obibok.pid`)
- Logs to `var/` directory
