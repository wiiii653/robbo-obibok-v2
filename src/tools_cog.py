"""Bot tools and help cog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .collection_loader import get_collection
from .discord_compat import commands, discord

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
        embed.add_field(
            name="Collection", value=col.name if col else state.collection_mode, inline=True
        )
        embed.add_field(name="Tracks Loaded", value=str(len(state.tracks)), inline=True)
        embed.add_field(name="Queue Size", value=str(len(state.queue)), inline=True)
        embed.add_field(name="Played", value=str(state.played_count), inline=True)
        embed.add_field(name="Looping", value="Yes" if state.is_looping else "No", inline=True)
        await ctx.send(embed=embed)

    @commands.command()
    async def health(self, ctx: commands.Context) -> None:
        """Show non-blocking runtime health diagnostics."""
        snapshot = self.bot.health_snapshot()
        embed = discord.Embed(title="Radio Health", color=0x2ECC71)
        embed.add_field(name="Status", value=str(snapshot["status"]), inline=True)
        embed.add_field(name="Uptime", value=f"{snapshot['uptime_seconds']}s", inline=True)
        embed.add_field(name="Guilds", value=str(snapshot["guilds"]), inline=True)
        embed.add_field(name="Playing", value=str(snapshot["playing_guilds"]), inline=True)
        embed.add_field(name="Active Streams", value=str(snapshot["active_streams"]), inline=True)
        embed.add_field(name="Monitor Tasks", value=str(snapshot["monitor_tasks"]), inline=True)
        embed.add_field(
            name="Lease Owner", value=str(snapshot["lease_owner"] or "none"), inline=True
        )
        metrics = snapshot["metrics"]
        embed.add_field(
            name="Failures",
            value=f"playback={metrics['playback_failures']}",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command()
    async def ocko(self, ctx: commands.Context) -> None:
        import random

        arts = [
            # 🦉 Sowy
            "🦉 **OCKO**\n      ___  \n     / _ \\ \n  _ | |_| |\n / | | __ |\n|  | | |_| |\n \\  \\|  _  |\n  \\   \\_/  |\n   |       |\n   |   |   |\n   |___|___|",
            "🦉 **OCKO**\n    .---.\n   / .-._)\n .\xb4:  _  `.\n |  (_)  |\n :       ;\n  `.___.\xb4",
            '🦉 **OCKO**\n  ,___,\n  {o,o}\n  |)__)\n  -"--"-\n  m   m',
            "🦉 **OCKO**\n    ___  \n   (o o) \n  (  V  )\n  --m-m---",
            "🦉 **OCKO**\n  .------.\n  |O  O  |\n  |  V   |\n  `------\xb4\n    ww ww",
            # 🐺 Wilk (dla Boruty)
            "🐺 **WILK**\n    __       __\n   /  \\\\\\.-./  \\\\\n   \\\\   (o o)   /\n    \\\\   U   /\n    /\\\\  -  /\\\\\n   /  \\\\/ \\\\/  \\\\\n  / /\\      /\\ \\\\\n  \\\\/_/ \\\\  / \\\\_\\\\\n     /_/    \\_\\",
            "🐺 **WILK**\n       __\n      /  \\\\\n     / . .\\\\\n    /  \\___/\n   /  /\n  /  /\n /  /\n/  /\n\\  \\\n \\  \\\n  \\  \\\n   \\  \\\n    \\__\\\\",
            # 🐻 Niedźwiedź
            '🐻 **MIŚ**\n    (\\_/)\n    (o.o)\n    ( > )\n   /"""""\\\\\n  /       \\\\\n |  ___   |\n | |___|  |\n  \\_______/',
            # 🐱 Kot
            '🐱 **KOT**\n    /\\_/\\\\\n   ( o.o )\n    > ^ <\n   /"""""\\\\\n  |       |\n  |  _   _|\n  | |_| |_|\n   \\_______/\n    |     |\n    |     |\n    |_____|',
            # 🦊 Lis
            '🦊 **LIS**\n    /\\_/\\\\\n   ( ,_.)\n   / >{} >\n  /"""""\\\\\n /       \\\\\n|  ___   |\n| |___|  |\n \\_______/',
            # 🐉 Smok
            "🐉 **SMOK**\n      /\\\\\n     /  \\\\\n    /||  \\\\\n   / ||   \\\\\n  /  ||    \\\\\n /___||_____\\\\\n | __||__   |\n || (__)||  |\n ||    ||  |\n ||____||__|\n |______|",
            # 🐦 Ptak
            "🐦 **PTAK**\n   ___   \n  (   )\n (     )\n(       )\n \\  W  /\n  \\___/\n   | |\n   |_|",
            # 🦇 Nietoperz
            "🦇 **NIETOPERZ**\n    /\\/\\/\\/\\/\\\\\n   /  o    o  \\\\\n  /      ^     \\\\\n /   \\______/   \\\\\n/________________\\\\\n    |   ||   |\n    |   ||   |\n   /    ||    \\\\\n  /_____||_____\\\\",
            # 🐧 Pingwin
            "🐧 **PINGWIN**\n   .---.\n  /     \\\\\n | () () |\n  \\  ^  /\n   `. .´\n    | |\n    |_|",
            # 🐸 Żaba
            "🐸 **ŻABA**\n    _(o o)_\n  /   \\_/   \\\\\n / /\\   /\\ \\\\\n/ /  \\_/  \\ \\\\\n| /       \\ |\n||   ___   ||\n||  |_|_|  ||\n \\\\_________/\n  |       |\n  |    _  |\n  |___|_|_|",
            # 🦌 Jeleń
            "🦌 **JELEŃ**\n   /\\      /\\\\\n  /  \\\\    /  \\\\\n /    \\\\  /    \\\\\n/      \\\\/      \\\\\n  __   (  )   __\n /  \\\\  |  |  /  \\\\\n|    | |  | |    |\n|    | |  | |    |\n|    | |  | |    |\n|____| |__| |____|",
        ]
        await ctx.send(f"```\n{random.choice(arts)}\n```")

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
                "`!hvsc` / `!c64` — \U0001f7e3 C64 SID (~60 500)\n"
                "`!asma` — \U0001f7e2 Atari SAP (~6 300)\n"
                "`!mod` / `!modarchive` — \U0001f7e0 ModArchive (~175 000)\n"
                "`!ay` / `!zx` — \U0001f535 ZX Spectrum AY (~4 500)\n"
                "`!ym` / `!atarist` — \U0001f3b9 Atari ST YM (~7 200)\n"
                "`!tiny` / `!tm` — \U0001f3b5 Demoscene Modules (~550)\n"
                "`!kgen` / `!keygen` / `!k` — \U0001f50a Keygen Music (~4 800)"
            ),
            inline=False,
        )

        embed.add_field(
            name="\u2764\ufe0f Favorites & Blacklist",
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
            name="\U0001f527 Tools",
            value=(
                "`!stats` — Show bot stats\n`!health` — Runtime diagnostics\n`!ocko` — \U0001f989 ASCII owl"
            ),
            inline=False,
        )

        embed.set_footer(text="Made with \U0001f525 by the forest spirit — Boruta")
        await ctx.send(embed=embed)
