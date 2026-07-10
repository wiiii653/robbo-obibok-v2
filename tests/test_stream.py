"""Tests for the FFmpeg-backed Discord audio source."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.stream import MonitorAudioSource


class FakeStdout:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, size: int) -> bytes:
        data, self.data = self.data[:size], self.data[size:]
        return data


def make_process(data: bytes = b"", *, returncode: int | None = None) -> MagicMock:
    process = MagicMock()
    process.stdout = FakeStdout(data)
    process.poll.return_value = returncode
    return process


def test_read_returns_one_discord_frame():
    frame = b"x" * MonitorAudioSource.FRAME_SIZE
    process = make_process(frame)

    with patch("src.stream.subprocess.Popen", return_value=process):
        source = MonitorAudioSource(sink_name="robbo_bot")
        assert source.read() == frame


def test_read_restarts_ffmpeg_after_process_exit():
    first = make_process(returncode=1)
    second = make_process(b"y" * MonitorAudioSource.FRAME_SIZE)

    with (
        patch("src.stream.subprocess.Popen", side_effect=[first, second]),
        patch("src.stream.time.time", return_value=100.0),
    ):
        source = MonitorAudioSource(sink_name="robbo_bot")
        assert source.read() == b"y" * MonitorAudioSource.FRAME_SIZE


def test_read_stops_after_maximum_restarts():
    process = make_process(returncode=1)

    with patch("src.stream.subprocess.Popen", return_value=process):
        source = MonitorAudioSource(sink_name="robbo_bot")
        source._restart_count = source.MAX_RESTARTS
        assert source.read() == b""


def test_cleanup_terminates_running_process():
    process = make_process()

    with patch("src.stream.subprocess.Popen", return_value=process):
        source = MonitorAudioSource(sink_name="robbo_bot")
        source.cleanup()

    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)
