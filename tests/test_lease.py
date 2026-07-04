"""Tests for playback lease."""

from __future__ import annotations

from src.lease import PlaybackLease


class TestPlaybackLease:
    def test_acquire_and_release(self):
        lease = PlaybackLease()
        assert lease.acquire(1, "Guild One") is True
        assert lease.acquire(1, "Guild One") is True
        assert lease.acquire(2, "Guild Two") is False
        assert lease.owner_guild_id == 1
        lease.release()
        assert lease.owner_guild_id is None
        assert lease.acquire(2, "Guild Two") is True
