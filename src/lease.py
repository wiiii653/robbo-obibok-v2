"""Single-guild ownership of the shared playback backend."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackLease:
    _owner_guild_id: int | None = None
    _owner_guild_name: str | None = None

    @property
    def owner_guild_id(self) -> int | None:
        return self._owner_guild_id

    @property
    def owner_guild_name(self) -> str | None:
        return self._owner_guild_name

    def acquire(self, guild_id: int, guild_name: str) -> bool:
        if self._owner_guild_id is None or self._owner_guild_id == guild_id:
            self._owner_guild_id = guild_id
            self._owner_guild_name = guild_name
            return True
        return False

    def release(self) -> None:
        self._owner_guild_id = None
        self._owner_guild_name = None
