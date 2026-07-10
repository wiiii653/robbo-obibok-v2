"""Tests for diagnostics commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.tools_cog import ToolsCog


@pytest.mark.asyncio
async def test_health_command_sends_runtime_snapshot():
    bot = MagicMock()
    bot.health_snapshot.return_value = {
        "status": "ok",
        "guilds": 2,
        "playing_guilds": 1,
        "active_streams": 1,
        "monitor_tasks": 1,
        "predownload_tasks": 0,
        "lease_owner": 123,
    }
    ctx = MagicMock()
    ctx.send = AsyncMock()

    await ToolsCog(bot).health.callback(ToolsCog(bot), ctx)

    ctx.send.assert_awaited_once()
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.title == "Radio Health"
    assert {field.name for field in embed.fields} >= {"Status", "Active Streams", "Lease Owner"}
