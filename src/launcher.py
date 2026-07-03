"""Startup orchestration, signal handling, graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from .audio import AudioController
from .bot import ObibokBot
from .config import AppConfig, load_config
from .favorites import Favorites
from .monitor import TrackMonitor
from .playback import PlaybackEngine
from .queue import Blacklist

logger = logging.getLogger("robbo_obibok")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_dotenv(root_dir: str) -> None:
    env_path = Path(root_dir) / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                os.environ.setdefault(key, value)


def create_bot(config: AppConfig) -> ObibokBot:
    root_dir = config.root_dir

    audio = AudioController(sink_name=config.audio.sink_name)
    audio.setup()
    favorites = Favorites(root_dir)
    blacklist = Blacklist(root_dir)
    engine = PlaybackEngine(audio=audio, favorites=favorites, blacklist=blacklist, root_dir=root_dir)
    monitor = TrackMonitor(audio=audio, empty_timeout=config.auto.empty_timeout)

    bot = ObibokBot(
        engine=engine,
        monitor=monitor,
        root_dir=root_dir,
        sink_name=config.audio.sink_name,
        command_prefix=config.command_prefix,
        guild_id=config.guild_id,
        auto_start_channel=config.auto.start_channel,
        empty_timeout=config.auto.empty_timeout,
    )

    return bot


def write_pid() -> None:
    pid_path = Path(__file__).resolve().parent.parent / "obibok.pid"
    pid_path.write_text(str(os.getpid()))


def remove_pid() -> None:
    pid_path = Path(__file__).resolve().parent.parent / "obibok.pid"
    if pid_path.exists():
        pid_path.unlink()


def main() -> None:
    setup_logging()
    config = load_config()

    load_dotenv(config.root_dir)
    config.token = os.environ.get("DISCORD_BOT_TOKEN", config.token)

    if not config.token:
        logger.error("No DISCORD_BOT_TOKEN set. Add it to .env or environment.")
        sys.exit(1)

    logger.info("Starting Robbo Obibok v2...")
    logger.info("Root: %s", config.root_dir)
    logger.info("Archive: %s", config.archive_path)

    bot = create_bot(config)

    write_pid()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown():
        logger.info("Shutting down...")
        remove_pid()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    try:
        bot.run(config.token)
    except KeyboardInterrupt:
        pass
    finally:
        remove_pid()
        logger.info("Goodbye.")
