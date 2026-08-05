"""Tests for the playback control permission helper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cog_shared import can_control_playback, require_control


class FakePermissions:
    def __init__(self, administrator: bool) -> None:
        self.administrator = administrator


class FakeMember:
    def __init__(self, member_id: int, guild: SimpleNamespace, *, admin: bool = False) -> None:
        self.id = member_id
        self.guild = guild
        self.guild_permissions = FakePermissions(admin)


def _make_guild(owner_id: int) -> SimpleNamespace:
    return SimpleNamespace(owner_id=owner_id)


def _make_bot(owner_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(owner_id=owner_id)


class TestCanControlPlayback:
    def test_admin_can_control(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(2, guild, admin=True)
        assert can_control_playback(_make_bot(), member) is True

    def test_server_owner_can_control(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(1, guild)
        assert can_control_playback(_make_bot(), member) is True

    def test_bot_owner_can_control(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(99, guild)
        bot = _make_bot(owner_id=99)
        assert can_control_playback(bot, member) is True

    def test_regular_member_cannot_control(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(2, guild)
        assert can_control_playback(_make_bot(), member) is False

    def test_none_member_rejected(self) -> None:
        assert can_control_playback(_make_bot(), None) is False

    def test_member_without_guild_rejected(self) -> None:
        member = FakeMember(1, None)
        assert can_control_playback(_make_bot(), member) is False

    def test_bot_owner_unknown_falls_back_to_server_rules(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(2, guild)
        bot = _make_bot(owner_id=None)
        assert can_control_playback(bot, member) is False


class TestRequireControl:
    @pytest.mark.asyncio
    async def test_allows_privileged(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(1, guild)
        ctx = SimpleNamespace(author=member, send=None)
        assert await require_control(_make_bot(), ctx) is True

    @pytest.mark.asyncio
    async def test_denies_regular_member_and_sends_message(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(2, guild)
        sent: list[str] = []

        async def fake_send(msg: str) -> None:
            sent.append(msg)

        ctx = SimpleNamespace(author=member, send=fake_send)
        assert await require_control(_make_bot(), ctx) is False
        assert len(sent) == 1
        assert "server owner" in sent[0]

    @pytest.mark.asyncio
    async def test_denies_without_send_crash(self) -> None:
        guild = _make_guild(owner_id=1)
        member = FakeMember(2, guild)
        ctx = SimpleNamespace(author=member, send=None)
        assert await require_control(_make_bot(), ctx) is False

    @pytest.mark.asyncio
    async def test_missing_author_rejected(self) -> None:
        ctx = SimpleNamespace(author=None, send=None)
        assert await require_control(_make_bot(), ctx) is False
