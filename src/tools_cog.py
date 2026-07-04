"""Bot tools and help cog."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from .collection_loader import get_collection

if TYPE_CHECKING:
    from .bot import ObibokBot


class ToolsCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot: ObibokBot = bot

    @commands.command()
    async def stats(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        col = get_collection(state.collection_mode)
        embed = discord.Embed(title="Radio Stats", color=0x3498DB)
        embed.add_field(name="Collection", value=col.name if col else state.collection_mode, inline=True)
        embed.add_field(name="Tracks Loaded", value=str(len(state.tracks)), inline=True)
        embed.add_field(name="Queue Size", value=str(len(state.queue)), inline=True)
        embed.add_field(name="Played", value=str(state.played_count), inline=True)
        embed.add_field(name="Looping", value="Yes" if state.is_looping else "No", inline=True)
        await ctx.send(embed=embed)

    @commands.command()
    async def ocko(self, ctx: commands.Context) -> None:
        owl = """
    ___________
   /           \\
  /  O       O  \\
 |    \\     /    |
  \\    \\___/    /
   \\           /
    \\_________/
        """
        await ctx.send(f"```\n{owl}\n```")

    @commands.command()
    async def help(self, ctx: commands.Context, command: str = "") -> None:
        embed = discord.Embed(
            title="🤖 Robbo Obibok v2 — Help",
            description=(
                "Seven collections, one bot — **the biggest chiptune radio on Discord.**\n"
                "Join a voice channel and `!play`!"
            ),
            color=0x2ECC71,
        )

        embed.add_field(
            name="🎮 Playback",
            value=(
                "`!play` / `!pl` — Start shuffled radio\n"
                "`!play <query>` — Search and play\n"
                "`!play <number>` — Play from search results\n"
                "`!stop` / `!st` — Stop and disconnect\n"
                "`!skip` / `!next` / `!nt` — Skip to next\n"
                "`!jump <n>` — Jump to track N\n"
                "`!np` — Now playing info\n"
                "`!queue` / `!q` — Show queue\n"
                "`!history` — Last 10 tracks\n"
                "`!sleep <min>` — Stop after N minutes\n"
                "`!loop` — Toggle repeat\n"
                "`!volume <0-200>` — Set volume\n"
                "`!clear` — Clear queue"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎵 Collections",
            value=(
                "`!flip` / `!switch` / `!toggle` / `!fl` — Cycle collection\n"
                "`!status` / `!mode` / `!collection` — Show current collection\n"
                "`!search <query>` — Search tracks\n"
                "`!hvsc` / `!c64` — 🟣 C64 SID (~60 500)\n"
                "`!asma` — 🟢 Atari SAP (~6 300)\n"
                "`!mod` / `!modarchive` — 🟠 ModArchive (~175 000)\n"
                "`!ay` / `!zx` — 🔵 ZX Spectrum AY (~4 500)\n"
                "`!ym` / `!atarist` — 🎹 Atari ST YM (~7 200)\n"
                "`!tiny` / `!tm` — 🎵 Demoscene Modules (~550)\n"
                "`!kgen` / `!keygen` / `!k` — 🔊 Keygen Music (~4 800)"
            ),
            inline=False,
        )

        embed.add_field(
            name="❤️ Favorites & Blacklist",
            value=(
                "`!favorites` / `!favs` — Show your favorites\n"
                "`!favplay` / `!fp` — Play favorites\n"
                "`!favsave` / `!pls` — Save favorites as playlist\n"
                "`!favload` / `!fpl` — Load a saved playlist\n"
                "`!playlists` / `!plist` — List saved playlists\n"
                "`!blk` — Blacklist current track\n"
                "`!blks` — Show blacklist\n"
                "`!blkrm <n>` — Remove blacklist item"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔧 Tools",
            value=(
                "`!stats` — Show bot stats\n"
                "`!ocko` — 🦉 ASCII owl"
            ),
            inline=False,
        )

        embed.set_footer(text="Made with 🔥 by the forest spirit — Boruta")
        await ctx.send(embed=embed)
