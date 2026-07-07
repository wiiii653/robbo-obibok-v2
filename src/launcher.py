"""Startup orchestration and graceful shutdown."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .audio import AudioController, check_audacious_version
from .bot import ObibokBot
from .config import AppConfig, load_config
from .favorites import Favorites
from .monitor import TrackMonitor
from .playback import PlaybackEngine
from .queue import Blacklist

logger = logging.getLogger("robbo_obibok")


def setup_logging(root_dir: str = "") -> None:
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=log_datefmt,
    )
    # Also write to a rotating file under var/ when root_dir is given
    if root_dir:
        from logging.handlers import RotatingFileHandler
        log_dir = Path(root_dir) / "var"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            str(log_dir / "robbo-obibok.log"),
            maxBytes=10_485_760,  # 10 MB
            backupCount=3,
        )
        handler.setFormatter(logging.Formatter(log_format, log_datefmt))
        root = logging.getLogger()
        root.addHandler(handler)
        # Keep discord.py from flooding the log with debug
        logging.getLogger("discord").setLevel(logging.WARNING)


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
    # Load per-format volumes from config (merges over defaults)
    import yaml
    try:
        raw_cfg = yaml.safe_load(Path(root_dir, "config.yaml").read_text()) or {}
        fv = raw_cfg.get("format_volumes", {})
        if isinstance(fv, dict) and fv:
            from .audio import load_format_volumes_from_dict
            load_format_volumes_from_dict(fv)
            logger.info("Loaded format_volumes from config: %s", fv)
    except Exception as exc:
        logger.warning("Failed to load format_volumes from config: %s", exc)
    favorites = Favorites(root_dir)
    blacklist = Blacklist(root_dir)
    engine = PlaybackEngine(
        audio=audio,
        favorites=favorites,
        blacklist=blacklist,
        root_dir=root_dir,
        archive_root=config.archive_path,
        shuffle_queue=config.playback.shuffle,
        default_loop=config.playback.loop,
    )
    monitor = TrackMonitor(audio=audio, empty_timeout=config.auto.empty_timeout)

    bot = ObibokBot(
        engine=engine,
        monitor=monitor,
        root_dir=root_dir,
        sink_name=config.audio.sink_name,
        command_prefix=config.command_prefix,
        guild_id=config.guild_id,
        auto_start_channel=config.auto.start_channel,
        default_loop=config.playback.loop,
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
    setup_logging(root_dir=os.getcwd())
    config = load_config()

    load_dotenv(config.root_dir)
    config.token = os.environ.get("DISCORD_BOT_TOKEN", config.token)

    if not config.token:
        logger.error("No DISCORD_BOT_TOKEN set. Add it to .env or environment.")
        sys.exit(1)

    try:
        check_audacious_version()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    logger.info("Starting Robbo Obibok v2...")
    logger.info("Root: %s", config.root_dir)
    logger.info("Archive: %s", config.archive_path)

    bot = create_bot(config)

    write_pid()

    try:
        bot.run(config.token)
    except KeyboardInterrupt:
        pass
    finally:
        remove_pid()
        logger.info("Goodbye.")
