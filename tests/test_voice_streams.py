"""Tests for Discord stream ownership."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.voice_streams import VoiceStreamManager


class FakeSource:
    def __init__(self, *, sink_name: str) -> None:
        self.sink_name = sink_name
        self.source_id = 0
        self._closed = False
        self.cleaned_up = False

    def cleanup(self) -> None:
        self.cleaned_up = True


def test_start_replaces_previous_stream(monkeypatch):
    monkeypatch.setattr("src.voice_streams.MonitorAudioSource", FakeSource)
    on_end = MagicMock()
    manager = VoiceStreamManager("robbo_bot", on_end)
    voice_client = MagicMock()
    voice_client.is_connected.return_value = True

    assert manager.start(123, voice_client) is True
    first = manager.get(123)
    assert first is not None

    assert manager.start(123, voice_client) is True
    assert first.cleaned_up is True
    assert manager.count == 1
    voice_client.play.assert_called()


def test_stream_callback_only_removes_current_source(monkeypatch):
    monkeypatch.setattr("src.voice_streams.MonitorAudioSource", FakeSource)
    manager = VoiceStreamManager("robbo_bot", MagicMock())
    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    manager.start(123, voice_client)
    source = manager.get(123)
    assert source is not None

    assert manager.remove_if_current(123, source.source_id + 1) is False
    assert manager.contains(123) is True
    assert manager.remove_if_current(123, source.source_id) is True
    assert manager.count == 0
