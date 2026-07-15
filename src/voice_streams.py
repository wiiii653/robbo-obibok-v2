"""Discord voice-stream lifecycle management.

This module owns only the Discord audio source. Playback selection, monitor
tasks, and reconnect policy stay with their respective services.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .discord_compat import discord
from .stream import MonitorAudioSource

logger = logging.getLogger(__name__)

StreamEndCallback = Callable[[int, Exception | None, int], None]


class VoiceStreamManager:
    """Own the active Discord audio sources for the bot."""

    def __init__(self, sink_name: str, on_stream_end: StreamEndCallback) -> None:
        self._sink_name = sink_name
        self._on_stream_end = on_stream_end
        self._streams: dict[int, MonitorAudioSource] = {}

    @property
    def count(self) -> int:
        return len(self._streams)

    def guild_ids(self) -> tuple[int, ...]:
        return tuple(self._streams)

    def contains(self, guild_id: int) -> bool:
        return guild_id in self._streams

    def get(self, guild_id: int) -> MonitorAudioSource | None:
        return self._streams.get(guild_id)

    def start(self, guild_id: int, voice_client: discord.VoiceClient) -> bool:
        """Replace the stream for a connected voice client."""
        if not voice_client or not voice_client.is_connected():
            logger.warning("start: voice client not connected for guild %s", guild_id)
            return False

        self.stop(guild_id)
        source = MonitorAudioSource(sink_name=self._sink_name)
        source_id = id(source)
        source.source_id = source_id
        voice_client.stop()
        voice_client.play(
            source,
            after=lambda error: self._on_stream_end(guild_id, error, source_id),
        )
        self._streams[guild_id] = source
        return True

    def stop(self, guild_id: int) -> None:
        """Release the source for one guild without disconnecting voice."""
        source = self._streams.pop(guild_id, None)
        if source is None:
            return
        source._closed = True
        source.cleanup()

    def remove_if_current(self, guild_id: int, source_id: int) -> bool:
        """Forget a source only when its callback belongs to the current stream."""
        source = self._streams.get(guild_id)
        if source is None or getattr(source, "source_id", None) != source_id:
            return False
        self._streams.pop(guild_id, None)
        return True

    def close(self) -> None:
        for guild_id in self.guild_ids():
            self.stop(guild_id)
