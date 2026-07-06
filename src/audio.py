"""Audio pipeline — PulseAudio sink, Audacious lifecycle, playback control."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_VOLUME = 0
MAX_VOLUME = 200

# Format-based volume — extension → volume percentage (default: 100)
FORMAT_VOLUMES: dict[str, int] = {
    "sid": 115,
    "mod": 115,
    "xm": 115,
    "s3m": 115,
    "it": 115,
}

_audacious_ready = False
SUPPORTED_AUDACIOUS_VERSION = "4.6.1"
AUDACIOUS_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")


def setup_sink(sink_name: str) -> bool:
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    if sink_name in result.stdout:
        return True
    try:
        created = subprocess.run(
            [
                "pactl", "load-module", "module-null-sink",
                f"sink_name={sink_name}",
                "sink_properties=device.description=Robbo_Obibok",
            ],
            capture_output=True,
        )
    except OSError:
        return False
    return created.returncode == 0


def get_audacious_version() -> str | None:
    try:
        result = subprocess.run(
            ["audtool", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = AUDACIOUS_VERSION_RE.search(result.stdout)
    if not match:
        return None
    return match.group(1)


def check_audacious_version(required_version: str = SUPPORTED_AUDACIOUS_VERSION) -> str | None:
    version = get_audacious_version()
    if version is None:
        logger.warning("Could not determine Audacious version")
        return None
    if version != required_version:
        raise RuntimeError(
            f"Unsupported Audacious version {version}; expected {required_version}"
        )
    logger.info("Audacious version verified: %s", version)
    return version


def start_player(sink_name: str = "robbo_bot") -> bool:
    global _audacious_ready
    if _audacious_ready:
        if _is_audacious_alive():
            return True
        _audacious_ready = False

    proc = subprocess.Popen(
        ["audacious", "--headless"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PULSE_SINK": sink_name},
    )
    try:
        for _ in range(20):
            version = get_audacious_version()
            if version:
                logger.info("Audacious version detected: %s", version)
                _audacious_ready = True
                return True
            time.sleep(1)
        logger.warning("Audacious D-Bus not ready after 20s")
        return False
    finally:
        if not _audacious_ready and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass


def kill_player() -> None:
    _audtool_call("playback-stop")
    subprocess.run(["pkill", "-x", "audacious"], capture_output=True)


UNSUPPORTED_SAP_TYPES = {"D", "E"}


def _get_sap_type(filepath: str) -> str | None:
    """Read the first ~5 lines of an SAP file and return its TYPE value."""
    try:
        with open(filepath, "r", encoding="ascii", errors="replace") as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip().rstrip("\r")
                if stripped.startswith("TYPE "):
                    return stripped[5:].strip()
    except OSError:
        pass
    return None


def _get_sap_songs_count(filepath: str) -> int | None:
    """Read the SAP header and return SONGS count, or None."""
    try:
        with open(filepath, "r", encoding="ascii", errors="replace") as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip().rstrip("\r")
                if stripped.startswith("SONGS "):
                    try:
                        return int(stripped[6:].strip())
                    except (ValueError, IndexError):
                        return None
    except OSError:
        return None
    return None


def _is_sap_supported(filepath: str) -> tuple[bool, str]:
    """Check if an SAP file has a TYPE that GME's Console plugin can play.

    Returns (supported: bool, reason: str).
    """
    if not filepath.lower().endswith(".sap"):
        return True, ""
    sap_type = _get_sap_type(filepath)
    if sap_type is None:
        return True, ""
    if sap_type in UNSUPPORTED_SAP_TYPES:
        return False, f"SAP TYPE {sap_type} not supported by Audacious Console plugin (GME 0.6.4)"
    return True, ""


def play_file(filepath: str, sink_name: str) -> bool:
    if not _audacious_ready:
        start_player(sink_name)
    logger.info("play_file: path=%s exists=%s", filepath, os.path.exists(filepath))
    # Fast-fail on known-unsupported formats (e.g. SAP TYPE D)
    supported, reason = _is_sap_supported(filepath)
    if not supported:
        logger.warning("play_file: REFUSED — %s, filepath=%s — skipping", reason, filepath)
        return False
    _audtool_call("playlist-clear")
    time.sleep(0.3)  # wait for Audacious to finish clearing the playlist
    add_ok = _audtool_call("playlist-addurl", filepath)
    play_ok = _audtool_call("playback-play")
    logger.info("play_file: add=%s play=%s", add_ok, play_ok)
    for attempt in range(3):
        time.sleep(0.2)
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


def current_song() -> str:
    """Return the song title as reported by Audacious (audtool current-song)."""
    result = subprocess.run(
        ["audtool", "current-song"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def current_song_filename() -> str:
    """Return the full filepath of the currently playing song."""
    result = subprocess.run(
        ["audtool", "current-song-filename"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


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


def set_volume_for_playback(filepath: str, sink_name: str) -> None:
    """Set volume based on the file extension (format-based volume)."""
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    vol = FORMAT_VOLUMES.get(ext, 100)
    set_volume(sink_name, vol)
    logger.info("Volume set to %d%% for format .%s", vol, ext if ext else "?")


def load_format_volumes_from_dict(volumes: dict[str, int]) -> None:
    """Update FORMAT_VOLUMES from a user config dict (merges over defaults)."""
    FORMAT_VOLUMES.update({k: int(v) for k, v in volumes.items()})


def enable_compressor() -> None:
    _audtool_call("plugin-enable", "compressor", "on")
    logger.info("Audacious Compressor plugin enabled")


def enable_console_plugin() -> None:
    _audtool_call("plugin-enable", "Console", "on")
    logger.info("Audacious Console plugin enabled (SAP/AY/YM)")


def enable_sid_plugin() -> None:
    _audtool_call("plugin-enable", "SID", "on")
    logger.info("Audacious SID plugin enabled")


def setup_sid_config() -> None:
    _audtool_call("config-set", "SID Player:playMaxTimeEnable", "TRUE")
    _audtool_call("config-set", "SID Player:playMaxTime", "180")
    _audtool_call("config-set", "SID Player:playMaxTimeUnknown", "TRUE")
    logger.info("Audacious SID plugin config set")


def ensure_audacious(sink_name: str = "robbo_bot") -> None:
    if _audacious_ready and _is_audacious_alive():
        return
    logger.warning("Health watchdog: Audacious not responsive, restarting...")
    kill_player()
    start_player(sink_name)


def _is_audacious_alive() -> bool:
    result = subprocess.run(["pgrep", "-x", "audacious"], capture_output=True)
    if result.returncode != 0:
        logger.warning("Health watchdog: pgrep audacious returned %d", result.returncode)
        return False
    alive = get_audacious_version() is not None
    if not alive:
        logger.warning("Health watchdog: audtool version failed (process exists but D-Bus unresponsive)")
    return alive


def _move_to_sink(sink_name: str) -> None:
    env = {**os.environ, "LC_ALL": "C"}
    result = subprocess.run(
        ["pactl", "list", "sink-inputs"],
        capture_output=True, text=True, env=env,
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
    _last_filepath: str = ""

    def setup(self) -> None:
        if not setup_sink(self.sink_name):
            logger.error("Failed to set up PulseAudio sink %s", self.sink_name)
            return
        if start_player(self.sink_name):
            setup_sid_config()
            enable_compressor()
            enable_console_plugin()
            enable_sid_plugin()

    def play(self, filepath: str) -> bool:
        self._last_filepath = filepath
        return play_file(filepath, self.sink_name)

    def stop(self) -> None:
        stop_playback()

    def kill(self) -> None:
        kill_player()

    def is_playing(self) -> bool:
        return is_playing()

    async def async_is_playing(self) -> bool:
        return await asyncio.to_thread(is_playing)

    def output_length(self) -> int:
        return output_length()

    async def async_output_length(self) -> int:
        return await asyncio.to_thread(output_length)

    def song_length(self) -> int:
        return song_length()

    async def async_song_length(self) -> int:
        return await asyncio.to_thread(song_length)

    def current_song(self) -> str:
        return current_song()

    def current_song_filename(self) -> str:
        return current_song_filename()

    def total_sap_time(self) -> int | None:
        """Return total playback time for multi-subsong SAP, or None.

        GME ignores the TIME fields in the SAP header (those are for the
        original Atari player). Instead, use the per-subsong length from
        audtool (actual GME playback duration) × number of SONGS.
        """
        fname = self._last_filepath or current_song_filename()
        if not fname.lower().endswith(".sap"):
            return None
        songs = _get_sap_songs_count(fname)
        if songs is None or songs <= 1:
            return None
        per_subsong = song_length()
        if per_subsong <= 0:
            return None
        return per_subsong * songs

    async def async_current_song(self) -> str:
        return await asyncio.to_thread(current_song)

    def get_volume(self) -> int | None:
        return get_volume(self.sink_name)

    def set_volume(self, volume: int) -> None:
        set_volume(self.sink_name, volume)

    def set_volume_for_playback(self, filepath: str) -> None:
        set_volume_for_playback(filepath, self.sink_name)

    async def async_set_volume_for_playback(self, filepath: str) -> None:
        return await asyncio.to_thread(set_volume_for_playback, filepath, self.sink_name)

    def ensure_ready(self) -> None:
        if setup_sink(self.sink_name):
            ensure_audacious(self.sink_name)
