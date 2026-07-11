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
_audacious_process: subprocess.Popen | None = None
SUPPORTED_AUDACIOUS_VERSION = "4.6.1"
AUDACIOUS_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")


def setup_sink(sink_name: str) -> bool:
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True,
            text=True,
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
                "pactl",
                "load-module",
                "module-null-sink",
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
        raise RuntimeError(f"Unsupported Audacious version {version}; expected {required_version}")
    logger.info("Audacious version verified: %s", version)
    return version


def start_player(sink_name: str = "robbo_bot") -> bool:
    global _audacious_process, _audacious_ready
    if _audacious_ready:
        if _is_audacious_alive():
            return True
        _audacious_ready = False

    # Never terminate a desktop user's Audacious session.  This process owns
    # only the child it starts and can safely clean up that child on restart.
    kill_player()

    proc = subprocess.Popen(
        ["audacious", "--headless"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PULSE_SINK": sink_name},
    )
    _audacious_process = proc
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
        if not _audacious_ready:
            _audacious_process = None


def kill_player() -> None:
    global _audacious_process, _audacious_ready
    _audtool_call("playback-stop")
    proc = _audacious_process
    _audacious_process = None
    _audacious_ready = False
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass


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


def _parse_sap_time(time_str: str) -> int | None:
    """Parse a SAP TIME value (MM:SS or MM:SS.xxx) to seconds, or None."""
    time_str = time_str.strip()
    if not time_str:
        return None
    parts = time_str.split(":")
    if len(parts) < 2:
        return None
    try:
        minutes = int(parts[0])
        sec_parts = parts[1].split(".")
        seconds = int(sec_parts[0])
        total = minutes * 60 + seconds
        return total if total > 0 else None
    except (ValueError, IndexError):
        return None


def _get_sap_time_seconds(filepath: str) -> int | None:
    """Read the SAP header and return TOTAL time in seconds, or None.

    Returns the SUM of all TIME fields found — for multi-song SAP with
    varying subsong durations this correctly accounts for each subsong.
    For single-song SAP returns the single TIME value.
    Falls back to first TIMExSONGS if fewer TIME lines than SONGS.

    SAP format::
        TIME 03:20           -> 200s
        TIME 03:20.09        -> 200s (ms truncated)
        TIME 02:57.133       -> 177s
        TIME 01:29.80 LOOP   -> 89s (LOOP suffix ignored)
    """
    times: list[int] = []
    try:
        with open(filepath, "r", encoding="ascii", errors="replace") as f:
            for _ in range(30):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip().rstrip("\r")
                if stripped.startswith("TIME "):
                    raw = stripped[5:].strip()
                    raw = raw.split()[0] if raw else ""  # first token (ignore LOOP/LOOP suffix)
                    result = _parse_sap_time(raw)
                    if result is not None:
                        times.append(result)
    except OSError:
        pass

    if not times:
        return None

    songs = _get_sap_songs_count(filepath)
    if songs is not None and songs > 1 and len(times) < songs:
        # Fewer TIME lines than SONGS — fall back to first × count
        return times[0] * songs

    return sum(times)


def _sap_has_loop(filepath: str) -> bool:
    """Return whether an SAP TIME header contains the LOOP flag."""
    try:
        with open(filepath, "r", encoding="ascii", errors="replace") as f:
            for _ in range(30):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip().rstrip("\r")
                if stripped.upper().startswith("TIME "):
                    fields = stripped.split()
                    if any(field.upper() == "LOOP" for field in fields[2:]):
                        return True
    except OSError:
        pass
    return False


def _get_ay_max_track(filepath: str) -> int:
    """Read the AY (ZXAYEMUL) header and return max_track, or 0.

    max_track byte at offset 16 gives the highest track index
    (0-based), so total songs = max_track + 1. Returns 0 (single
    track) on any error or non-AY file.

    Only lower 4 bits are the track count — upper bits may carry
    flags (common in AY headers), so they are masked out.
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read(20)
    except OSError:
        return 0
    if len(data) < 20 or data[:8] != b"ZXAYEMUL":
        return 0
    return data[16] & 0x0F


def _get_sid_songs_count(filepath: str) -> int:
    """Read the SID (PSID/RSID) header and return number of songs, or 1.

    The number of songs is a big-endian word at offset 14 (0x0E).
    Returns 1 (single song) on any error or non-SID file.
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read(18)
    except OSError:
        return 1
    if len(data) < 16:
        return 1
    magic = data[:4]
    if magic not in (b"PSID", b"RSID"):
        return 1
    songs = (data[14] << 8) | data[15]
    return max(songs, 1)


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
    for attempt in range(5):  # 5 retries with actual re-play
        time.sleep(0.5)  # wait longer (0.5s instead of 0.2s)
        if _audtool_call("playback-playing"):
            _move_to_sink(sink_name)
            logger.info("play_file: playing after attempt %d", attempt + 1)
            return True
        # On attempts 2+, re-clear and re-add — some formats need a fresh kick
        # (GME/SID plugins may need more time or a re-init for certain files)
        if attempt >= 1:
            logger.warning("play_file: attempt %d not playing, re-adding...", attempt + 1)
            _audtool_call("playlist-clear")
            time.sleep(0.2)
            _audtool_call("playlist-addurl", filepath)
            _audtool_call("playback-play")
        else:
            # First failure: just re-kick playback without clearing
            logger.warning("play_file: attempt %d failed, re-kicking playback", attempt + 1)
            _audtool_call("playback-stop")
            time.sleep(0.1)
            _audtool_call("playback-play")
    # One final sanity check: is the file actually loaded?
    loaded_file = current_song_filename()
    if loaded_file:
        logger.warning(
            "play_file: FAILED after 5 retries but file loaded (%s), trying play once more",
            loaded_file,
        )
        _audtool_call("playback-play")
        time.sleep(1.0)
        if _audtool_call("playback-playing"):
            _move_to_sink(sink_name)
            logger.info("play_file: playing after final kick")
            return True
    _audtool_call("playlist-clear")
    logger.warning("play_file: FAILED after 5 attempts, filepath=%s — will retry later", filepath)

    # If Audacious died, restart it and try one more time
    if not _is_audacious_alive():
        logger.warning("play_file: Audacious DEAD, restarting and retrying...")
        kill_player()
        start_player(sink_name)
        _audtool_call("playlist-clear")
        time.sleep(0.3)
        _audtool_call("playlist-addurl", filepath)
        _audtool_call("playback-play")
        for attempt in range(5):
            time.sleep(0.5)
            if _audtool_call("playback-playing"):
                _move_to_sink(sink_name)
                logger.info("play_file: playing after restart (attempt %d)", attempt + 1)
                return True
            if attempt >= 1:
                _audtool_call("playlist-clear")
                time.sleep(0.2)
                _audtool_call("playlist-addurl", filepath)
                _audtool_call("playback-play")
            logger.warning("play_file: restart retry attempt %d failed", attempt + 1)
        _audtool_call("playlist-clear")
        logger.error("play_file: STILL FAILED after restart, filepath=%s", filepath)

    return False


def stop_playback() -> None:
    _audtool_call("playback-stop")
    _audtool_call("playlist-clear")


def is_playing() -> bool:
    return _audtool_call("playback-playing")


def output_length() -> int:
    try:
        result = subprocess.run(
            ["audtool", "current-song-output-length-seconds"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1
    try:
        return int(result.stdout.strip())
    except (ValueError, OSError):
        return -1


def song_length() -> int:
    try:
        result = subprocess.run(
            ["audtool", "current-song-length-seconds"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1
    try:
        return int(result.stdout.strip())
    except (ValueError, OSError):
        return -1


def current_song() -> str:
    """Return the song title as reported by Audacious (audtool current-song)."""
    try:
        result = subprocess.run(
            ["audtool", "current-song"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def current_song_filename() -> str:
    """Return the full filepath of the currently playing song."""
    try:
        result = subprocess.run(
            ["audtool", "current-song-filename"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def get_volume(sink_name: str) -> int | None:
    try:
        result = subprocess.run(
            ["pactl", "get-sink-volume", sink_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)%", result.stdout)
    return int(m.group(1)) if m else None


def set_volume(sink_name: str, volume: int) -> None:
    clamped = max(MIN_VOLUME, min(MAX_VOLUME, volume))
    try:
        subprocess.run(
            ["pactl", "set-sink-volume", sink_name, f"{clamped}%"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("Could not set PulseAudio sink volume for %s", sink_name)


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


def disable_repeat() -> None:
    """Disable playlist repeat so GME doesn't loop finished tracks."""
    try:
        result = subprocess.run(
            ["audtool", "playlist-repeat-status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = result.stdout.strip().lower() if result.returncode == 0 else ""
        if status == "off":
            logger.info("Audacious playlist repeat already off")
            return
        if status == "on":
            if (
                subprocess.run(
                    ["audtool", "playlist-repeat-toggle"], capture_output=True
                ).returncode
                == 0
            ):
                logger.info("Audacious playlist repeat disabled")
                return
        # Status unknown — try toggling
        if (
            subprocess.run(["audtool", "playlist-repeat-toggle"], capture_output=True).returncode
            == 0
        ):
            logger.info("Audacious playlist repeat toggled (assumed off now)")
            return
    except OSError:
        pass
    logger.warning("Could not disable Audacious playlist repeat")


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
        logger.warning(
            "Health watchdog: audtool version failed (process exists but D-Bus unresponsive)"
        )
    return alive


def _move_to_sink(sink_name: str) -> None:
    env = {**os.environ, "LC_ALL": "C"}
    result = subprocess.run(
        ["pactl", "list", "sink-inputs"],
        capture_output=True,
        text=True,
        env=env,
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
            capture_output=True,
            timeout=10,
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
            disable_repeat()

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
        """Return total playback time for SAP, or None.

        Uses max(header TIME sum, GME song_length) to prevent early
        cut-off — some SAP files have header TIME shorter than actual
        GME playback (e.g. Nekrofil: TIME=44s, GME=52s — header alone
        would cut 8s early).

        Trade-off: if GME over-reports (Crocketts Theme: TIME=200s,
        GME=208-285s), max() preserves the inflated value, causing
        some looping before wall-clock timeout fires. This is preferred
        over early cut-off (which is silent data loss rather than
        audible redundancy).

        For multi-song SAP: GME total = per_subsong × SONGS.
        Header total = sum of all TIME lines from SAP header.
        """
        fname = self._last_filepath or current_song_filename()
        if not fname.lower().endswith(".sap"):
            return None

        # 1) Header-derived total (sum of all TIME lines)
        header_total = _get_sap_time_seconds(fname)

        # 2) GME-derived total (song_length × SONGS)
        gme_per = song_length()
        if gme_per <= 0:
            gme_total = None
        else:
            songs = _get_sap_songs_count(fname)
            if songs is not None and songs > 1:
                gme_total = gme_per * songs
            else:
                gme_total = gme_per

        # 3) Use max of both, falling back to whichever is available
        if header_total is not None and gme_total is not None:
            return max(header_total, gme_total)
        if header_total is not None:
            return header_total
        if gme_total is not None:
            return gme_total
        return None

    def sap_has_loop(self) -> bool:
        fname = self._last_filepath or current_song_filename()
        return fname.lower().endswith(".sap") and _sap_has_loop(fname)

    def total_ay_time(self) -> int | None:
        """Return total playback time for multi-track AY, or None.

        Reads max_track from the AY (ZXAYEMUL) header (byte at offset 16,
        0-based max track index) and multiplies the per-subsong length
        from audtool by (max_track + 1).
        """
        fname = self._last_filepath or current_song_filename()
        if not fname.lower().endswith(".ay"):
            return None
        max_track = _get_ay_max_track(fname)
        if max_track <= 0:
            return None
        per_subsong = song_length()
        if per_subsong <= 0:
            return None
        return per_subsong * (max_track + 1)

    def total_sid_time(self) -> int | None:
        """Return total playback time for multi-song SID, or None.

        SID files can contain multiple subtunes. Audacious cycles
        through all subtunes via playMaxTime=180s each, so the
        total playback time is song_length() × number of songs.
        """
        fname = self._last_filepath or current_song_filename()
        if not (
            fname.lower().endswith(".sid")
            or fname.lower().endswith(".psid")
            or fname.lower().endswith(".rsid")
        ):
            return None
        songs = _get_sid_songs_count(fname)
        if songs <= 1:
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
