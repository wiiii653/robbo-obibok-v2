<p align="center">
  <pre>
    __________        ___.   ___.                ________  ___.    .__ ___.             __     
    \______   \  ____ \_ |__ \_ |__    ____      \_____  \ \_ |__  |__|\_ |__    ____  |  | __ 
     |       _/ /  _ \ | __ \ | __ \  /  _ \      /   |   \ | __ \ |  | | __ \  /  _ \ |  |/ / 
     |    |   \(  <_> )| \_\ \| \_\ \(  <_> )    /    |    \| \_\ \|  | | \_\ \(  <_> )|    <  
     |____|_  / \____/ |___  /|___  / \____/     \_______  /|___  /|__| |___  / \____/ |__|_ \ 
            \/             \/     \/                     \/     \/          \/              \/
  </pre>
</p>

<p align="center">
  <img src="extras/robbo-banner.png" alt="Robbo Obibok Banner" width="600">
</p>

# Robbo Obibok v2 — The Ultimate Chiptune Bot

Named after a fusion of the 1989 Polish Atari classic *Robbo* and the avant-garde jazz band *Robotobibok*, this specialized Discord bot streams vintage retro chipmusic. Blending intricate technical grooves with retro charm, Robbo plays from **seven collections** spanning Atari, C64, ZX Spectrum, Amiga, demoscene keygens, and beyond.

**Join a voice channel, type `!play`, and let the chips play.**

## What's New in v2

Complete rewrite with a **flat, minimal architecture** — 17 source modules instead of 76, 150+ tests, same features. No more entrypoint facades, runtime assemblies, or compatibility layers.

## Features

- 🎵 **Seven collections** — switch between ASMA (Atari SAP, 6 300+), HVSC (C64 SID, 60 000+), AY (ZX Spectrum, 4 500+), YM (Atari ST, 7 200+), ModArchive (Amiga/PC tracker modules, 175 000+), Tiny Music modules (~550), and KGen (demoscene keygen music, 4 800+)
- 🔀 **Shuffle loop** — never hear the same track twice in a row
- 🎼 **Rich metadata** — track name, composer, copyright from headers
- ❤️ **Favorites playlist** — react to any Now Playing embed to save/remove tracks
- ⏭️ **Skip**, **Stop**, **Now Playing**, **Stats**, **Search**
- 🔄 **Auto-advance** — moves to next track when current ends, with chiptune-aware monitoring
- 🧩 **Subsong playback** — demoscene/module tracks advance through embedded parts
- 💾 **Queue persistence** — restores compatible queues across restarts
- 🌐 **Remote playback cache** — direct URLs are downloaded into `var/downloads/` before playback
- 📻 **Auto-start** — starts playing when someone joins a configured voice channel
- 🌙 **Auto-stop** — disconnects after the channel is empty for `auto.empty_timeout`
- 🛡️ **Playback lease + watchdog** — one guild owns playback at a time, with automatic audio recovery
- ⚙️ **Configurable** via `config.yaml`, including the archive root path
- 📀 **Local archives** — all collections served from disk, no remote crawling at runtime
- 🧭 **Richer monitor heuristics** — output-drop confirmation and format-aware timeout handling

## Commands

| Command | Description |
|---------|-------------|
| **Playback** | |
| `!play` / `!pl` | Start shuffled radio from current collection |
| `!play <query>` | Search, or play a direct URL, and immediately start the first match |
| `!play <number>` | Play a track from last search results |
| `!stop` / `!st` | Stop playback and disconnect |
| `!skip` / `!next` / `!nt` | Skip to next track |
| `!jump <n>` | Jump to track N in queue |
| `!np` | Show current track info |
| `!queue` / `!q` | Show upcoming tracks |
| `!history` | Show last 10 played tracks |
| `!sleep <min>` | Stop playback after N minutes |
| `!loop` | Toggle repeat current track |
| `!volume <0-200>` | Set playback volume |
| `!clear` | Clear the queue |
| **Collections** | |
| `!flip` / `!switch` / `!toggle` / `!fl` | Rotate through all available collections |
| `!status` / `!mode` / `!collection` | Show current collection and queue info |
| `!search <query>` | Search tracks by name, directory, or author |
| `!hvsc` / `!c64` / `!sid` | Switch to **Commodore 64 SID** (~60 500) |
| `!asma` | Switch to **Atari SAP** (~6 300) |
| `!mod` / `!modarchive` / `!modules` | Switch to **ModArchive tracker modules** (~175 000) |
| `!ay` / `!spectrum` / `!zx` | Switch to **ZX Spectrum AY** (~4 500) |
| `!ym` / `!atarist` | Switch to **Atari ST YM** (~7 200) |
| `!tiny` / `!tm` | Switch to **Tiny Music modules** (~550) |
| `!kgen` / `!keygen` / `!k` | Switch to **Keygen Music** (~4 800) |
| **Favorites & Blacklist** | |
| `!favorites` / `!favs` | Show your reaction-based favorites playlist |
| `!favplay` / `!fp` | Play favorites in shuffle mode |
| `!favsave` / `!pls` | Save current favorites as a named playlist |
| `!favload` / `!fpl` | Load and play a saved playlist |
| `!playlists` / `!plist` | List all saved playlists |
| `!blk` | Blacklist the currently playing track |
| `!blks` | Show blacklist |
| `!blkrm <n>` | Remove track N from blacklist |
| **Tools & Info** | |
| `!stats` | Show radio stats (uptime, tracks played) |
| `!export` | Export queue as plain text |
| `!ocko` | Display an ASCII owl |

### Favorites System

React with **any emoji** to a Now Playing embed to save the track to your favorites. React again to remove it (toggle). Data persists in `favorites.json`.

## Collections

| Collection | Format | Tracks | Source |
|------------|--------|--------|--------|
| **ASMA** | `.sap` | 6 335 | Local `archiwum/asma/` |
| **HVSC** | `.sid` | 60 811 | Local `archiwum/hvsc/C64Music/` |
| **AY** | `.ay` | 4 550 | Local `archiwum/ay/` |
| **YM** | `.ym` | 7 266 | Local `archiwum/ym/` |
| **ModArchive** | `.mod`, `.xm`, `.s3m`, `.it` | 175 000+ | Local `archiwum/modarchive/` |
| **Tiny Music** | `.mod`, `.xm`, `.s3m`, `.it` | ~550 | Local `archiwum/tiny/` |
| **KGen** | `.mod`, `.xm`, `.s3m`, `.it` | 4 843 | Local `archiwum/kgen/` |

Local archives are served from disk; remote URLs are cached before playback.

## Quick Start

Supported Python versions: **3.11+**.

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-venv audacious audacious-plugins ffmpeg pipewire-pulse gstreamer1.0-plugins-good gstreamer1.0-plugins-bad sidplayfp

git clone git@github.com:wiiii653/robbo-obibok-v2.git
cd robbo-obibok-v2
make install
```

### Fedora

```bash
sudo dnf install -y python3 python3-virtualenv audacious audacious-plugins ffmpeg pipewire-utils gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-plugins-bad-freeworld sidplayfp

git clone git@github.com:wiiii653/robbo-obibok-v2.git
cd robbo-obibok-v2
make install
```

### Arch Linux

```bash
sudo pacman -S python python-virtualenv audacious audacious-plugins ffmpeg pipewire gst-plugins-good gst-plugins-bad sidplayfp

git clone git@github.com:wiiii653/robbo-obibok-v2.git
cd robbo-obibok-v2
make install
```

## Running

```bash
cd robbo-obibok-v2
source venv/bin/activate

# Set your bot token
export DISCORD_BOT_TOKEN="your-token-here"

# Run via the launcher
./run_bot.sh
```

Development checks:

```bash
make test        # Unit tests
make lint        # Ruff linter
make format      # Ruff formatter
```

## Invite the Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your bot application → **OAuth2 → URL Generator**
3. Scopes: `bot`, `applications.commands`
4. Permissions: `Send Messages`, `Connect`, `Speak`, `Use Voice Activity`
5. Use the generated URL to invite the bot to your server

## Systemd Service (Linux)

Run as a background service:

```bash
# Copy the service file
mkdir -p ~/.config/systemd/user
cp deploy/robbo-obibok.service ~/.config/systemd/user/

# Store token in the environment file used by the service
printf 'DISCORD_BOT_TOKEN="%s"\n' "YOUR_TOKEN_HERE" > ~/robbo-obibok-v2/.env
chmod 600 ~/robbo-obibok-v2/.env

# Enable and start
systemctl --user daemon-reload
systemctl --user enable robbo-obibok
systemctl --user start robbo-obibok

# Check logs
journalctl --user -u robbo-obibok -f
```

## Building Local Indexes

After cloning, build the local track indexes for the local archive collections:

```bash
make build-indexes

# or run the builders directly
python scripts/build_asma_index.py   # indexes all .sap files in archiwum/asma/
python scripts/build_hvsc_index.py   # indexes all .sid files in archiwum/hvsc/C64Music/
python scripts/build_ay_index.py     # indexes all .ay files in archiwum/ay/
python scripts/build_ym_index.py     # indexes all .ym files in archiwum/ym/
python scripts/build_tiny_index.py   # indexes all .mod/.xm/.it/.s3m files in archiwum/tiny/
python scripts/build_kgen_index.py   # indexes keygen music modules
python scripts/build_modarchive_index.py  # indexes ModArchive modules
```

These generate `*_cache_local.json` files for instant startup — no crawling at runtime.
Collection files are resolved under the configurable `archive.path` root.

## Configuration

Edit `config.yaml`:

```yaml
command_prefix: "!"
# Optional: restrict to a single server
# guild_id: 123456789012345678
audio:
  sink_name: "robbo_bot"
playback:
  loop: false           # true repeats the current track
  shuffle: true
archive:
  path: "archiwum"
auto:
  start_channel: ""      # voice channel name (empty = disabled)
  empty_timeout: 60      # seconds before disconnect when empty
```

## File Structure

```
robbo-obibok-v2/
├── src/                     # Source modules (17 files)
│   ├── models.py            # Collection and PlaybackState
│   ├── persistence.py       # JSON file I/O
│   ├── collection_loader.py # Collection registry, index loaders, metadata
│   ├── audio.py             # PulseAudio + Audacious control
│   ├── stream.py            # Voice stream source
│   ├── queue.py             # Queue shuffle, blacklist, persistence
│   ├── favorites.py         # Reaction favorites + named playlists
│   ├── playback.py          # Playback orchestrator
│   ├── subsong.py           # Subsong detection + conversion
│   ├── lease.py             # Single-guild playback ownership
│   ├── monitor.py           # Track completion detection
│   ├── remote.py            # Remote download + cache helpers
│   ├── embeds.py            # Discord rich embed builders
│   ├── bot.py               # Discord bot commands + events
│   ├── config.py            # YAML config loading
│   ├── launcher.py          # Startup, signals, shutdown
│   └── __main__.py          # python -m src entry point
├── tests/                   # 150+ unit tests
├── scripts/                 # Index builder scripts
├── deploy/                  # systemd service files
├── extras/                  # Assets (banner, avatar)
├── config.yaml              # Runtime configuration
├── pyproject.toml           # Dependencies + tool config
├── Makefile                 # Build/test commands
├── run_bot.sh               # Entrypoint wrapper
```

## Audio Effects

The bot enables Audacious's **Compressor** effect plugin at startup for consistent loudness across collections.

To verify: `audtool plugin-is-enabled compressor`
To adjust: edit `~/.config/audacious/config` and restart the bot.

## Troubleshooting

| Symptom | Likely Fix |
|---------|-----------|
| `RuntimeError: PyNaCl library needed` | `pip install pynacl` |
| Bot doesn't respond to commands | Enable **Message Content Intent** in Discord Developer Portal |
| Bot joins VC but no sound | Audacious not running — restart bot, or run `audacious --headless` manually |
| `!play` says "Join a voice channel" | You must be in a voice channel when issuing the command |
| Bot auto-disconnects too fast | Increase `auto.empty_timeout` in config |
| SID metadata is empty | Some SID files lack embedded headers — filename is shown as fallback |
