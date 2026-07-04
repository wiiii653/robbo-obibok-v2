"""Audio pipeline — PulseAudio sink, Audacious lifecycle, playback control."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass

from .models import COLLECTIONS

logger = logging.getLogger(__name__)

MIN_VOLUME = 0
MAX_VOLUME = 200

COLLECTION_VOLUMES: dict[str, int] = {
    col.id: col.volume for col in COLLECTIONS.values()
}

_audacious_ready = False


def setup_sink(sink_name: str) -> bool:
    result = subprocess.run(
        ["pactl", "list", "sinks", "short"],
        capture_output=True, text=True,
    )
    if sink_name in result.stdout:
        return True
    subprocess.run(
        [
            "pactl", "load-module", "module-null-sink",
            f"sink_name={sink_name}",
            "sink_properties=device.description=Robbo_Obibok",
        ],
        capture_output=True,
    )
    return True


def start_player(sink_name: str = "robbo_bot") -> bool:
    global _audacious_ready
    if _audacious_ready:
        if _is_audacious_alive():
            return True
        _audacious_ready = False

    subprocess.Popen(
        ["audacious", "--headless"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PULSE_SINK": sink_name},
    )
    for _ in range(20):
        if _audtool_call("version"):
            _audacious_ready = True
            return True
        time.sleep(1)
    logger.warning("Audacious D-Bus not ready after 20s")
    return False


def kill_player() -> None:
    _audtool_call("playback-stop")
    subprocess.run(["pkill", "-x", "audacious"], capture_output=True)


def play_file(filepath: str, sink_name: str) -> bool:
    if not _audacious_ready:
        start_player(sink_name)
    logger.info("play_file: path=%s exists=%s", filepath, os.path.exists(filepath))
    _audtool_call("playlist-clear")
    add_ok = _audtool_call("playlist-addurl", filepath)
    play_ok = _audtool_call("playback-play")
    logger.info("play_file: add=%s play=%s", add_ok, play_ok)
    for attempt in range(3):
        time.sleep(1)
        if _audtool_call("playback-playing"):
            _move_to_sink(sink_name)
            logger.info("play_file: playing after attempt %d", attempt + 1)
            return True
        logger.warning("play_file: attempt %d failed, retrying", attempt + 1)
    _audtool_call("playlist-clear")
    logger.warning("play_file: FAILED after 3 attempts, filepath=%s — will retry later", filepath)
    return False


def stop_playback() -> None:
    _audtool_call("playback-stop")
    _audtool_call("playlist-clear")


def is_playing() -> bool:
    return _audtool_call("playback-playing")


def output_length() -> int:
    result = subprocess.run(
        ["audtool", "current-song-output-length-seconds"],
        capture_output=True, text=True, timeout=10,
    )
    try:
        return int(result.stdout.strip())
    except (ValueError, OSError):
        return -1


def song_length() -> int:
    result = subprocess.run(
        ["audtool", "current-song-length-seconds"],
        capture_output=True, text=True, timeout=10,
    )
    try:
        return int(result.stdout.strip())
    except (ValueError, OSError):
        return -1


def get_volume(sink_name: str) -> int | None:
    result = subprocess.run(
        ["pactl", "get-sink-volume", sink_name],
        capture_output=True, text=True,
    )
    m = re.search(r"(\d+)%", result.stdout)
    return int(m.group(1)) if m else None


def set_volume(sink_name: str, volume: int) -> None:
    clamped = max(MIN_VOLUME, min(MAX_VOLUME, volume))
    subprocess.run(
        ["pactl", "set-sink-volume", sink_name, f"{clamped}%"],
        capture_output=True,
    )


def set_volume_for_collection(collection_id: str, sink_name: str) -> None:
    vol = COLLECTION_VOLUMES.get(collection_id, 100)
    set_volume(sink_name, vol)
    logger.info("Volume set to %d%% for collection %s", vol, collection_id)


def enable_compressor() -> None:
    _audtool_call("plugin-enable", "compressor", "TRUE")
    logger.info("Audacious Compressor plugin enabled")


def setup_sid_config() -> None:
    _audtool_call("config-set", "SID Player:playMaxTimeEnable", "TRUE")
    _audtool_call("config-set", "SID Player:playMaxTime", "180")
    _audtool_call("config-set", "SID Player:playMaxTimeUnknown", "TRUE")
    logger.info("Audacious SID plugin config set")


def ensure_audacious(sink_name: str = "robbo_bot") -> None:
    if _audacious_ready and _is_audacious_alive():
        return
    kill_player()
    start_player(sink_name)


def _is_audacious_alive() -> bool:
    result = subprocess.run(["pgrep", "-x", "audacious"], capture_output=True)
    if result.returncode != 0:
        return False
    return bool(_audtool_call("version"))


def _move_to_sink(sink_name: str) -> None:
    result = subprocess.run(
        ["pactl", "list", "sink-inputs"],
        capture_output=True, text=True,
    )
    for block in result.stdout.split("Sink Input #")[1:]:
        index, _, details = block.partition("\n")
        if not index.strip().isdigit():
            continue
        details_lower = details.lower()
        is_audacious = (
            'application.name = "audacious"' in details_lower
            or 'application.process.binary = "audacious"' in details_lower
        )
        if is_audacious:
            subprocess.run(
                ["pactl", "move-sink-input", index.strip(), sink_name],
                capture_output=True,
            )
            logger.info("Moved audacious to sink %s", sink_name)


def _audtool_call(*args: str) -> bool:
    try:
        result = subprocess.run(
            ["audtool", *args],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@dataclass(slots=True)
class AudioController:
    sink_name: str = "robbo_bot"

    def setup(self) -> None:
        setup_sink(self.sink_name)
        if start_player(self.sink_name):
            setup_sid_config()
            enable_compressor()

    def play(self, filepath: str) -> bool:
        return play_file(filepath, self.sink_name)

    def stop(self) -> None:
        stop_playback()

    def kill(self) -> None:
        kill_player()

    def is_playing(self) -> bool:
        return is_playing()

    def output_length(self) -> int:
        return output_length()

    def song_length(self) -> int:
        return song_length()

    def get_volume(self) -> int | None:
        return get_volume(self.sink_name)

    def set_volume(self, volume: int) -> None:
        set_volume(self.sink_name, volume)

    def set_collection_volume(self, collection_id: str) -> None:
        set_volume_for_collection(collection_id, self.sink_name)

    def ensure_ready(self) -> None:
        setup_sink(self.sink_name)
        ensure_audacious(self.sink_name)
