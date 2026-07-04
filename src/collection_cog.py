"""Collection switching and search cog."""

from __future__ import annotations

import discord
from discord.ext import commands

from .collection_loader import flip_collection, get_collection, load_raw_paths
from .embeds import status_embed


class CollectionCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.command(aliases=["switch", "toggle", "fl"])
    async def flip(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        new_id = flip_collection(state.collection_mode)
        await self._switch(ctx, new_id)

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
        state.search_collection_id = state.collection_mode
        lines = [self.bot.engine.describe_search_result(r, state.collection_mode, i + 1) for i, r in enumerate(results[:10])]
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
        active = state.is_playing or bool(ctx.voice_client)
        if active and (not ctx.author.voice or not ctx.author.voice.channel):
            await ctx.send("Join a voice channel before switching active playback.")
            return
        if active and not self.bot.try_acquire_lease(ctx.guild):
            owner = self.bot.playback_lease.owner_guild_name or "another server"
            await ctx.send(f"Music is already playing in **{owner}**.")
            return

        if active:
            await self.bot.engine.stop(state)
            self.bot._stop_stream(ctx.guild.id)
            self.bot._cancel_predownload(ctx.guild.id)
            self.bot._cancel_monitor(ctx.guild.id)
            if ctx.voice_client:
                await ctx.voice_client.disconnect()

        state.collection_mode = collection_id
        state.tracks = []
        state.queue = []
        state.queue_collection_ids = []
        state.position = 0
        state.current_track = ""
        state.current_collection_id = ""
        state.is_looping = self.bot.default_loop
        state.search_results = []
        state.search_collection_id = ""
        col = get_collection(collection_id)
        await ctx.send(f"{col.flip_tag} **Switched to {col.name}**" if col else f"Switched to {collection_id}")
        if not active:
            return
        try:
            await ctx.author.voice.channel.connect()
            state.voice_channel_id = ctx.author.voice.channel.id
            track = await self.bot.engine.start_radio(state, collection_id=collection_id, user_id=ctx.author.id)
            if not track:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                self.bot.release_lease(ctx.guild.id)
                await ctx.send("No tracks in this collection.")
                return
            cog = self.bot.get_cog("PlaybackCog")
            if cog:
                await cog._play_and_monitor(ctx, state)
        except Exception as exc:
            cog = self.bot.get_cog("PlaybackCog")
            if cog:
                await cog._finish_playback(ctx, state, f"Failed to switch collection: {exc}")
            else:
                self.bot.release_lease(ctx.guild.id)
                await ctx.send(f"Failed to switch collection: {exc}")
