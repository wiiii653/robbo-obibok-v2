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

## Architecture — Layered Hexagonal

```
src/robbo_obibok/
├── domain/                 # Pure config + state models (NO asyncio, NO discord, NO aiohttp)
│   ├── config.py           # AppConfig, PlaybackConfig, PathConfig, ArchiveConfig
│   ├── archive_config.py   # ArchiveRuntimeConfig
│   ├── collection_state.py # Collection state models
│   └── queue_state.py      # Queue state models
├── application/            # Pure command + playback policies (NO infrastructure imports)
│   ├── command_policy.py   # Command authorization rules
│   └── playback_policy.py  # Playback decision logic
├── infrastructure/         # Environment and persistence adapters
│   ├── environment.py      # System env access
│   └── persistence.py      # JSON file read/write
├── compatibility/          # Legacy entrypoint export policy + adapters
│   ├── bindings.py         # Entrypoint export graph
│   └── surface.py          # Stable surface aliases
├── bot_*.py                # Discord bot runtime, events, dependencies
├── playback_*.py           # Audio playback: process, service, monitor, volume, assets
├── entrypoint_*.py         # DI / composition root, lifecycle, bootstrap
├── runtime_*.py            # Runtime wiring, bindings, state, task manager
├── collection_*.py         # Collection specs, catalog, service
├── archive_*.py            # Archive abstraction, catalog, downloads, runtime
└── session_*.py            # Per-session context, playback deps
```

### Layer Rules (enforced by tests in test_architecture.py)

1. **domain/** must NOT import: discord, aiohttp, asyncio, subprocess, threading
2. **domain/** must be synchronous — no `async def` or `await`
3. **domain/** must NOT import upper layers (entrypoint_*, runtime_*, playback_*, bot_*, archive_*, collection_*)
4. **application/** must NOT import: aiohttp, discord, infrastructure, subprocess
5. Production code must NOT import legacy `domain_*.py` facades — import from `domain/` package
6. Import passive models from `*_models` modules, not from active modules (e.g., `bot_runtime_models` not `bot_runtime`)
7. Import protocols from `entrypoint_state_protocols`, not from `entrypoint_state`

## Project Structure

```
robbo-obibok-v2/
├── src/
│   └── robbo_obibok/           # Installable Python package
│       ├── domain/             # Pure domain layer
│       ├── application/        # Application policies
│       ├── infrastructure/     # IO adapters
│       └── compatibility/      # Legacy compat layer
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
- Architecture boundary tests enforce layer rules via AST analysis
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
