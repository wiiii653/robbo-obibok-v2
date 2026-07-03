"""Discord bot — commands, events, voice connection."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import discord
from discord.ext import commands

from .collection_loader import flip_collection, get_collection, load_raw_paths
from .embeds import now_playing_embed, queue_embed, status_embed
from .models import PlaybackState
from .monitor import TrackMonitor
from .playback import PlaybackEngine

logger = logging.getLogger(__name__)


class ObibokBot(commands.Bot):
    def __init__(
        self,
        engine: PlaybackEngine,
        monitor: TrackMonitor,
        root_dir: str,
        command_prefix: str = "!",
        guild_id: int | None = None,
        auto_start_channel: str = "",
        empty_timeout: int = 60,
    ) -> None:
        super().__init__(command_prefix=command_prefix, intents=discord.Intents.all())
        self.engine = engine
        self.monitor = monitor
        self.root_dir = root_dir
        self.guild_id = guild_id
        self.auto_start_channel = auto_start_channel
        self.empty_timeout = empty_timeout
        self._states: dict[int, PlaybackState] = {}
        self._monitor_tasks: dict[int, asyncio.Task] = {}
        self._np_messages: dict[int, dict[str, Any]] = {}

    def get_state(self, guild_id: int) -> PlaybackState:
        if guild_id not in self._states:
            self._states[guild_id] = PlaybackState(guild_id=guild_id)
        return self._states[guild_id]

    async def setup_hook(self) -> None:
        self.add_cog(PlaybackCog(self))
        self.add_cog(CollectionCog(self))
        self.add_cog(FavoritesCog(self))
        self.add_cog(ToolsCog(self))


class PlaybackCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot = bot

    @commands.command(aliases=["pl", "radio", "start"])
    async def play(self, ctx: commands.Context, *, query: str = "") -> None:
        if not ctx.guild:
            return
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Join a voice channel first!")

        state = self.bot.get_state(ctx.guild.id)

        if query.isdigit():
            idx = int(query) - 1
            if not state.search_results or idx < 0 or idx >= len(state.search_results):
                return await ctx.send("Invalid number. Use !search first.")
            path = state.search_results[idx]
            state.queue.append(path)
            state.position = len(state.queue) - 1
            await self._play_and_monitor(ctx, state)
            return

        if query:
            results = self.bot.engine.search(query, state)
            if not results:
                return await ctx.send(f"No tracks matching `{query}`.")
            state.search_results = results
            lines = [f"`{i+1}.` `{r.rsplit('/', 1)[-1]}`" for i, r in enumerate(results[:10])]
            return await ctx.send("\n".join(lines))

        if ctx.voice_client:
            await ctx.voice_client.disconnect()

        await ctx.author.voice.channel.connect()
        track = self.bot.engine.start_radio(state, user_id=ctx.author.id)
        if not track:
            return await ctx.send("No tracks in this collection. Run `make build-indexes` first.")

        state.voice_channel_id = ctx.author.voice.channel.id
        await ctx.send(f"Starting **{state.collection_mode.upper()}** radio...")
        await self._play_and_monitor(ctx, state)

    @commands.command(aliases=["st"])
    async def stop(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        await self.bot.engine.stop(state)
        task = self.bot._monitor_tasks.pop(ctx.guild.id, None)
        if task and not task.done():
            task.cancel()
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send("Stopped.")

    @commands.command(aliases=["next", "nt"])
    async def skip(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        track = await self.bot.engine.skip_track(state)
        if not track:
            return await ctx.send("Queue empty.")
        await self._play_and_monitor(ctx, state)

    @commands.command()
    async def np(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        if not state.current_track:
            return await ctx.send("Nothing playing.")
        col = get_collection(state.collection_mode)
        meta = self.bot.engine.get_track_metadata(state.current_track, state.collection_mode)
        title = meta.get("NAME", state.current_track.rsplit("/", 1)[-1])
        author = meta.get("AUTHOR", "Unknown")
        embed = now_playing_embed(
            title=title,
            author=author,
            collection_name=col.name if col else state.collection_mode,
            collection_icon=col.icon if col else "?",
            position=state.position + 1,
            total=len(state.queue),
        )
        msg = await ctx.send(embed=discord.Embed.from_dict(embed))
        self.bot._np_messages[msg.id] = {
            "filepath": state.current_track,
            "collection_id": state.collection_mode,
        }

    @commands.command(aliases=["q"])
    async def queue(self, ctx: commands.Context, page: int = 0) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        info = self.bot.engine.queue_info(state)
        embed = queue_embed(info, state.position, page)
        await ctx.send(embed=discord.Embed.from_dict(embed))

    @commands.command()
    async def history(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        if not state.history:
            return await ctx.send("No history yet.")
        lines = [f"`{i+1}.` `{h.rsplit('/', 1)[-1]}`" for i, h in enumerate(reversed(state.history[-10:]))]
        await ctx.send("\n".join(lines))

    @commands.command()
    async def jump(self, ctx: commands.Context, index: int) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        track = self.bot.engine.jump_to_track(state, index - 1)
        if not track:
            return await ctx.send("Invalid position.")
        await self._play_and_monitor(ctx, state)

    @commands.command()
    async def loop(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        looping = self.bot.engine.toggle_loop(state)
        await ctx.send(f"Loop: {'ON' if looping else 'OFF'}")

    @commands.command()
    async def volume(self, ctx: commands.Context, level: int = -1) -> None:
        if level < 0:
            vol = self.bot.engine.audio.get_volume()
            return await ctx.send(f"Volume: {vol}%" if vol else "Volume: unknown")
        self.bot.engine.audio.set_volume(level)
        await ctx.send(f"Volume set to {level}%")

    @commands.command()
    async def clear(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        await self.bot.engine.clear(state)
        await ctx.send("Queue cleared.")

    @commands.command()
    async def sleep(self, ctx: commands.Context, minutes: int = 5) -> None:
        await ctx.send(f"Stopping in {minutes} minutes...")
        await asyncio.sleep(minutes * 60)
        await self.stop(ctx)

    @commands.command()
    async def export(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        if not state.queue:
            return await ctx.send("Queue empty.")
        lines = [f"{i+1}. {t.rsplit('/', 1)[-1]}" for i, t in enumerate(state.queue)]
        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n..."
        await ctx.send(f"```\n{text}\n```")

    async def _play_and_monitor(self, ctx: commands.Context, state: PlaybackState) -> None:
        if not ctx.guild:
            return
        task = self.bot._monitor_tasks.pop(ctx.guild.id, None)
        if task and not task.done():
            task.cancel()

        track = await self.bot.engine.play_track(state)
        if not track:
            return await ctx.send("Failed to play track.")

        await self._send_now_playing(ctx, state)

        async def on_track_end(s: PlaybackState) -> None:
            next_t = await self.bot.engine.skip_track(s)
            if next_t:
                await self._play_and_monitor(ctx, s)

        self.bot._monitor_tasks[ctx.guild.id] = asyncio.create_task(
            self.bot.monitor.monitor_loop(state, on_track_end)
        )

    async def _send_now_playing(self, ctx: commands.Context, state: PlaybackState) -> None:
        meta = self.bot.engine.get_track_metadata(state.current_track, state.collection_mode)
        col = get_collection(state.collection_mode)
        title = meta.get("NAME", state.current_track.rsplit("/", 1)[-1])
        author = meta.get("AUTHOR", "")
        embed = now_playing_embed(
            title=title,
            author=author,
            collection_name=col.name if col else state.collection_mode,
            collection_icon=col.icon if col else "?",
            position=state.position + 1,
            total=len(state.queue),
        )
        msg = await ctx.send(embed=discord.Embed.from_dict(embed))
        self.bot._np_messages[msg.id] = {
            "filepath": state.current_track,
            "collection_id": state.collection_mode,
        }


class CollectionCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot = bot

    @commands.command(aliases=["switch", "toggle", "fl"])
    async def flip(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        new_id = flip_collection(state.collection_mode)
        state.collection_mode = new_id
        col = get_collection(new_id)
        await ctx.send(f"{col.flip_tag} **Switched to {col.name}**" if col else f"Switched to {new_id}")

    @commands.command(aliases=["mode", "collection"])
    async def status(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        col = get_collection(state.collection_mode)
        track_count = len(state.tracks) if state.tracks else 0
        embed = status_embed(
            collection_name=col.name if col else state.collection_mode,
            collection_icon=col.icon if col else "?",
            track_count=track_count,
            is_playing=state.is_playing,
            current_track=state.current_track.rsplit("/", 1)[-1] if state.current_track else "",
        )
        await ctx.send(embed=discord.Embed.from_dict(embed))

    @commands.command()
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        if not state.tracks:
            paths = load_raw_paths(state.collection_mode, self.bot.root_dir)
            if paths:
                state.tracks = paths
        results = self.bot.engine.search(query, state)
        if not results:
            return await ctx.send(f"No results for `{query}`.")
        state.search_results = results
        lines = [f"`{i+1}.` `{r.rsplit('/', 1)[-1]}`" for i, r in enumerate(results[:10])]
        await ctx.send("\n".join(lines))

    @commands.command(aliases=["c64", "sid"])
    async def hvsc(self, ctx: commands.Context) -> None:
        await self._switch(ctx, "hvsc")

    @commands.command()
    async def asma(self, ctx: commands.Context) -> None:
        await self._switch(ctx, "asma")

    @commands.command(aliases=["modarchive", "modules"])
    async def mod(self, ctx: commands.Context) -> None:
        await self._switch(ctx, "modarchive")

    @commands.command(aliases=["spectrum", "zx"])
    async def ay(self, ctx: commands.Context) -> None:
        await self._switch(ctx, "ay")

    @commands.command(aliases=["atarist"])
    async def ym(self, ctx: commands.Context) -> None:
        await self._switch(ctx, "ym")

    @commands.command(aliases=["tm"])
    async def tiny(self, ctx: commands.Context) -> None:
        await self._switch(ctx, "tiny")

    @commands.command(aliases=["keygen", "k"])
    async def kgen(self, ctx: commands.Context) -> None:
        await self._switch(ctx, "kgen")

    async def _switch(self, ctx: commands.Context, collection_id: str) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        state.collection_mode = collection_id
        col = get_collection(collection_id)
        await ctx.send(f"{col.flip_tag} **Switched to {col.name}**" if col else f"Switched to {collection_id}")


class FavoritesCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id:
            return
        msg_data = self.bot._np_messages.get(payload.message_id)
        if not msg_data:
            return
        self.bot.engine.toggle_favorite(
            payload.user_id,
            msg_data["filepath"],
            msg_data["collection_id"],
        )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id:
            return
        msg_data = self.bot._np_messages.get(payload.message_id)
        if not msg_data:
            return
        self.bot.engine.toggle_favorite(
            payload.user_id,
            msg_data["filepath"],
            msg_data["collection_id"],
        )

    @commands.command(aliases=["favs"])
    async def favorites(self, ctx: commands.Context) -> None:
        tracks = self.bot.engine.favorites.get_tracks(ctx.author.id)
        if not tracks:
            return await ctx.send("No favorites yet. React to Now Playing embeds!")
        lines = [f"`{i+1}.` `{t.get('title', t['filepath'].rsplit('/', 1)[-1])}`" for i, t in enumerate(tracks[:15])]
        await ctx.send(f"**Favorites ({len(tracks)}):**\n" + "\n".join(lines))

    @commands.command(aliases=["fp"])
    async def favplay(self, ctx: commands.Context) -> None:
        if not ctx.guild or not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Join a voice channel first!")
        tracks = self.bot.engine.favorites.get_tracks(ctx.author.id)
        if not tracks:
            return await ctx.send("No favorites yet.")
        state = self.bot.get_state(ctx.guild.id)
        state.queue = [t["filepath"] for t in tracks]
        random.shuffle(state.queue)
        state.position = 0
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.author.voice.channel.connect()
        state.voice_channel_id = ctx.author.voice.channel.id
        cog = self.bot.get_cog("PlaybackCog")
        if cog:
            await cog._play_and_monitor(ctx, state)

    @commands.command()
    async def blk(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        if self.bot.engine.blacklist_current(ctx.author.id, state):
            await ctx.send("Blacklisted.")
        else:
            await ctx.send("Nothing to blacklist.")

    @commands.command()
    async def blks(self, ctx: commands.Context) -> None:
        tracks = self.bot.engine.blacklist.get_tracks(ctx.author.id)
        if not tracks:
            return await ctx.send("Blacklist empty.")
        lines = [f"`{i+1}.` `{t.rsplit('/', 1)[-1]}`" for i, t in enumerate(tracks)]
        await ctx.send("**Blacklist:**\n" + "\n".join(lines))

    @commands.command()
    async def blkrm(self, ctx: commands.Context, index: int) -> None:
        removed = self.bot.engine.blacklist.remove_by_index(ctx.author.id, index - 1)
        if removed:
            await ctx.send(f"Removed `{removed.rsplit('/', 1)[-1]}`.")
        else:
            await ctx.send("Invalid index.")


class ToolsCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot = bot

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
        embed = discord.Embed(title="Robbo Obibok v2 — Commands", color=0x2ECC71)

        embed.add_field(
            name="Playback",
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
            name="Collections",
            value=(
                "`!flip` / `!fl` — Rotate collection\n"
                "`!status` — Current collection info\n"
                "`!search <query>` — Search tracks\n"
                "`!hvsc` / `!c64` — C64 SID (60k+)\n"
                "`!asma` — Atari SAP (6k+)\n"
                "`!mod` — ModArchive (175k+)\n"
                "`!ay` / `!zx` — ZX Spectrum AY (4k+)\n"
                "`!ym` / `!atarist` — Atari ST YM (7k+)\n"
                "`!tiny` / `!tm` — Tiny Music (550)\n"
                "`!kgen` / `!k` — Keygen Music (4.8k)"
            ),
            inline=False,
        )

        embed.add_field(
            name="Favorites & Blacklist",
            value=(
                "`!favorites` / `!favs` — Show favorites\n"
                "`!favplay` / `!fp` — Play favorites\n"
                "`!favsave` <name> — Save as playlist\n"
                "`!favload` <name> — Load playlist\n"
                "`!playlists` / `!plist` — List playlists\n"
                "`!blk` — Blacklist current track\n"
                "`!blks` — Show blacklist\n"
                "`!blkrm <n>` — Remove from blacklist"
            ),
            inline=False,
        )

        embed.add_field(
            name="Tools",
            value=(
                "`!stats` — Radio statistics\n"
                "`!export` — Export queue as text\n"
                "`!ocko` — ASCII owl"
            ),
            inline=False,
        )

        embed.set_footer(text="React to Now Playing embeds to save favorites!")
        await ctx.send(embed=embed)
