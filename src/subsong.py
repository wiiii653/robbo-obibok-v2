"""Minimal subsong detection and conversion helpers."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def get_subsongs(filepath: str) -> list[float]:
    durations: list[float] = []
    for subsong in range(20):
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-subsong",
                    str(subsong),
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_entries",
                    "format=duration",
                    filepath,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if not result.stdout.strip():
                break
            data = json.loads(result.stdout)
            duration = data.get("format", {}).get("duration")
            if duration is None:
                break
            durations.append(float(duration))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
            break
    return durations


def subsong_temp_path(root_dir: str, filepath: str, subsong: int) -> str:
    basename = os.path.basename(filepath).rsplit(".", 1)[0]
    safe = "".join(char if char.isalnum() or char in " _-" else "_" for char in basename)
    temp_dir = Path(root_dir) / "var" / "subsongs"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return str(temp_dir / f"{safe}_{subsong}.wav")


def convert_subsong(filepath: str, subsong: int, output_path: str) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-subsong",
                str(subsong),
                "-i",
                filepath,
                "-ac",
                "1",
                "-ar",
                "48000",
                "-f",
                "wav",
                output_path,
            ],
            capture_output=True,
            timeout=60,
        )
        return os.path.exists(output_path) and os.path.getsize(output_path) > 100
    except (OSError, subprocess.SubprocessError):
        return False


def cleanup_subsong_files(paths: list[str]) -> None:
    for wav in paths:
        if wav and os.path.exists(wav):
            try:
                os.remove(wav)
            except OSError:
                pass
