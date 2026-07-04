"""Playback command cog."""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from .cog_shared import FAVORITE_EMOJI, FakeContext, logger
from .collection_loader import get_collection, load_raw_paths
from .embeds import now_playing_embed, queue_embed
from .models import PlaybackState
from .remote import is_remote_track

if TYPE_CHECKING:
    from .bot import ObibokBot


class PlaybackCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot: ObibokBot = bot
        self._last_sent: tuple[str, int, float] = ("", 0, 0.0)  # (track, position, timestamp)
        self._last_auto_start: float = 0.0  # timestamp of last auto-start attempt

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Auto-reconnect on restart: if humans are in auto_start_channel, start playing."""
        if not self.bot.auto_start_channel:
            return
        await asyncio.sleep(3)  # let everything settle
        for guild in self.bot.guilds:
            if self.bot.guild_id is not None and guild.id != self.bot.guild_id:
                continue
            channel = discord.utils.get(guild.voice_channels, name=self.bot.auto_start_channel)
            if not channel:
                continue
            members = [m for m in channel.members if not m.bot]
            if not members:
                continue
            state = self.bot.get_state(guild.id)
            if state.is_playing:
                return
            if not self.bot.try_acquire_lease(guild):
                return
            self._last_auto_start = time.time()
            try:
                vc = await channel.connect()
                state.voice_channel_id = channel.id
                track = await self.bot.engine.start_radio(state, user_id=members[0].id)
                if not track:
                    self.bot.release_lease(guild.id)
                    await vc.disconnect()
                    return
                # Build a minimal fake ctx for _play_and_monitor
                ctx = FakeContext(guild, members[0], vc, send=channel.send)
                await self._play_and_monitor(ctx, state)
                logger.info("Auto-reconnect: resumed playback for %d users in %s", len(members), channel.name)
            except Exception as exc:
                logger.warning("Auto-reconnect failed: %s", exc)
                self.bot.release_lease(guild.id)
                if vc:
                    await vc.disconnect()

    async def _can_control_audio(self, ctx: commands.Context, *, require_owner: bool = False) -> bool:
        if not ctx.guild:
            return False
        owner_id = self.bot.playback_lease.owner_guild_id
        if owner_id is not None and owner_id != ctx.guild.id:
            owner = self.bot.playback_lease.owner_guild_name or "another server"
            await ctx.send(f"Music is currently controlled by **{owner}**.")
            return False
        if require_owner and owner_id != ctx.guild.id:
            await ctx.send("Nothing is playing on this server.")
            return False
        return True

    def _set_queue(self, state: PlaybackState, queued: list[tuple[str, str]], *, shuffle: bool = False) -> None:
        if shuffle:
            random.shuffle(queued)
        state.queue = [filepath for filepath, _ in queued]
        state.queue_collection_ids = [collection_id for _, collection_id in queued]
        state.position = 0
        state.is_looping = self.bot.default_loop

    async def _finish_playback(self, ctx: commands.Context, state: PlaybackState, message: str) -> None:
        guild_id = ctx.guild.id if ctx.guild else None
        try:
            await self.bot.engine.stop(state)
        except Exception as exc:
            logger.warning("Failed to stop audio during cleanup: %s", exc)
        if guild_id is not None:
            self.bot._stop_stream(guild_id)
            self.bot._cancel_predownload(guild_id)
        if guild_id is not None:
            self.bot._cancel_monitor(guild_id)
        self.bot.release_lease(guild_id)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send(message)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return
        if not self.bot.auto_start_channel:
            return
        if not member.guild:
            return
        if self.bot.guild_id is not None and member.guild.id != self.bot.guild_id:
            return
        if before.channel == after.channel:
            return
        if after.channel is None:
            return
        if after.channel.name != self.bot.auto_start_channel:
            return
        # Dedup: don't re-attempt auto-start within 10s
        now = time.time()
        if now - self._last_auto_start < 10:
            return
        state = self.bot.get_state(member.guild.id)
        if state.is_playing:
            return
        if not self.bot.try_acquire_lease(member.guild):
            return
        self._last_auto_start = time.time()
        vc = None
        try:
            vc = await after.channel.connect()
            track = await self.bot.engine.start_radio(state, user_id=member.id)
            if not track:
                self.bot.release_lease(member.guild.id)
                await vc.disconnect()
                return
            state.voice_channel_id = after.channel.id

            async def noop_send(*args, **kwargs):
                return None

            send_fn = after.channel.send if after.channel else noop_send
            ctx = FakeContext(member.guild, member, vc, send_fn)
            await self._play_and_monitor(ctx, state)
        except Exception as exc:
            await self.bot.engine.stop(state)
            self.bot._stop_stream(member.guild.id)
            self.bot._cancel_predownload(member.guild.id)
            self.bot._cancel_monitor(member.guild.id)
            self.bot.release_lease(member.guild.id)
            if vc:
                await vc.disconnect()
            logger.warning("Auto-start failed: %s", exc)

    @commands.command(aliases=["pl", "radio", "start"])
    async def play(self, ctx: commands.Context, *, query: str = "") -> None:
        if not ctx.guild:
            return
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Join a voice channel first!")

        state = self.bot.get_state(ctx.guild.id)

        if is_remote_track(query):
            if not self.bot.try_acquire_lease(ctx.guild):
                owner = self.bot.playback_lease.owner_guild_name or "another server"
                return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
            self.bot._cancel_predownload(ctx.guild.id)
            self._set_queue(state, [(query, state.collection_mode)])
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                await ctx.author.voice.channel.connect()
                state.voice_channel_id = ctx.author.voice.channel.id
                await ctx.send("Starting remote track...")
                await self._play_and_monitor(ctx, state)
            except Exception as exc:
                await self._finish_playback(ctx, state, f"Failed to play remote track: {exc}")
            return

        if query.isdigit():
            idx = int(query) - 1
            if not state.search_results or idx < 0 or idx >= len(state.search_results):
                return await ctx.send("Invalid number. Use !search first.")
            path = state.search_results[idx]
            if not self.bot.try_acquire_lease(ctx.guild):
                owner = self.bot.playback_lease.owner_guild_name or "another server"
                return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
            self.bot._cancel_predownload(ctx.guild.id)
            self._set_queue(state, [(path, state.search_collection_id or state.collection_mode)])
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                await ctx.author.voice.channel.connect()
                state.voice_channel_id = ctx.author.voice.channel.id
                await self._play_and_monitor(ctx, state)
            except Exception as exc:
                await self._finish_playback(ctx, state, f"Failed to play selection: {exc}")
            return

        if query:
            if not state.tracks:
                paths = load_raw_paths(state.collection_mode, self.bot.root_dir)
                if paths:
                    state.tracks = paths
            results = self.bot.engine.search(query, state)
            if not results:
                return await ctx.send(f"No tracks matching `{query}`.")
            if not self.bot.try_acquire_lease(ctx.guild):
                owner = self.bot.playback_lease.owner_guild_name or "another server"
                return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
            self.bot._cancel_predownload(ctx.guild.id)
            state.search_results = results
            state.search_collection_id = state.collection_mode
            self._set_queue(state, [(path, state.collection_mode) for path in results])
            try:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                await ctx.author.voice.channel.connect()
                state.voice_channel_id = ctx.author.voice.channel.id
                await ctx.send(f"Starting search result for `{query}`...")
                await self._play_and_monitor(ctx, state)
            except Exception as exc:
                await self._finish_playback(ctx, state, f"Failed to play search result: {exc}")
            return

        if ctx.voice_client:
            await ctx.voice_client.disconnect()

        if not self.bot.try_acquire_lease(ctx.guild):
            owner = self.bot.playback_lease.owner_guild_name or "another server"
            return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
        try:
            self.bot._cancel_predownload(ctx.guild.id)
            await ctx.author.voice.channel.connect()
            track = await self.bot.engine.start_radio(state, user_id=ctx.author.id)
            if not track:
                self.bot.release_lease(ctx.guild.id)
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                return await ctx.send("No tracks in this collection. Run `make build-indexes` first.")

            state.voice_channel_id = ctx.author.voice.channel.id
            await ctx.send(f"Starting **{state.collection_mode.upper()}** radio...")
            await self._play_and_monitor(ctx, state)
        except Exception as exc:
            await self._finish_playback(ctx, state, f"Failed to start playback: {exc}")

    @commands.command(aliases=["st"])
    async def stop(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        if not await self._can_control_audio(ctx):
            return
        state = self.bot.get_state(ctx.guild.id)
        await self.bot.engine.stop(state)
        self.bot._stop_stream(ctx.guild.id)
        self.bot._cancel_predownload(ctx.guild.id)
        self.bot._cancel_monitor(ctx.guild.id)
        self.bot.release_lease(ctx.guild.id)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send("Stopped.")

    @commands.command(aliases=["next", "nt"])
    async def skip(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        if not await self._can_control_audio(ctx, require_owner=True):
            return
        state = self.bot.get_state(ctx.guild.id)
        self.bot._cancel_monitor(ctx.guild.id)
        self.bot._cancel_predownload(ctx.guild.id)
        track = await self.bot.engine.skip_track(state)
        if not track:
            return await self._finish_playback(ctx, state, "Playlist ended.")
        await self._after_track_started(ctx, state)
        self._install_monitor(ctx, state)

    @commands.command()
    async def np(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        if not state.current_track:
            return await ctx.send("Nothing playing.")
        collection_id = state.current_collection_id or state.collection_mode
        col = get_collection(collection_id)
        meta = self.bot.engine.get_track_metadata(state.current_track, collection_id)
        title = self.bot.engine.audio.current_song()
        if not title:
            title = meta.get("NAME", "") or ""
        if not title:
            title = state.current_track.rsplit("/", 1)[-1]
        author = meta.get("AUTHOR", "Unknown")
        embed = now_playing_embed(
            title=title,
            author=author,
            collection_name=col.name if col else collection_id,
            collection_icon=col.icon if col else "?",
            position=state.position + 1,
            total=len(state.queue),
            color=col.color if col else 0x00FF00,
        )
        msg = await ctx.send(embed=discord.Embed.from_dict(embed))
        if msg is None:
            return
        self.bot._track_np_message(msg.id, {
            "filepath": state.current_track,
            "collection_id": collection_id,
        })
        await msg.add_reaction(FAVORITE_EMOJI)

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
        if not await self._can_control_audio(ctx, require_owner=True):
            return
        state = self.bot.get_state(ctx.guild.id)
        if index < 1 or index > len(state.queue):
            return await ctx.send("Invalid position.")
        self.bot._cancel_monitor(ctx.guild.id)
        self.bot._cancel_predownload(ctx.guild.id)
        track = await self.bot.engine.jump_to_track(state, index - 1)
        if not track:
            return await self._finish_playback(ctx, state, "Failed to play track.")
        await self._after_track_started(ctx, state)
        self._install_monitor(ctx, state)

    @commands.command()
    async def loop(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        looping = self.bot.engine.toggle_loop(state)
        await ctx.send(f"Loop: {'ON' if looping else 'OFF'}")

    @commands.command()
    async def volume(self, ctx: commands.Context, level: int = -1) -> None:
        if not await self._can_control_audio(ctx):
            return
        if level < 0:
            vol = self.bot.engine.audio.get_volume()
            return await ctx.send(f"Volume: {vol}%" if vol is not None else "Volume: unknown")
        self.bot.engine.audio.set_volume(level)
        await ctx.send(f"Volume set to {level}%")

    @commands.command()
    async def clear(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        if not await self._can_control_audio(ctx):
            return
        state = self.bot.get_state(ctx.guild.id)
        await self.bot.engine.clear(state)
        self.bot._stop_stream(ctx.guild.id)
        self.bot._cancel_predownload(ctx.guild.id)
        self.bot._cancel_monitor(ctx.guild.id)
        self.bot.release_lease(ctx.guild.id)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send("Queue cleared.")

    @commands.command()
    async def sleep(self, ctx: commands.Context, minutes: int = 5) -> None:
        if not ctx.guild:
            return
        if minutes <= 0:
            return await ctx.send("Sleep time must be greater than zero minutes.")
        if not await self._can_control_audio(ctx, require_owner=True):
            return
        session = self.bot._playback_sessions.get(ctx.guild.id, 0)
        await ctx.send(f"Stopping in {minutes} minutes...")
        await asyncio.sleep(minutes * 60)
        if self.bot._playback_sessions.get(ctx.guild.id, 0) != session:
            return
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
        if not ctx.voice_client:
            return await self._finish_playback(ctx, state, "Voice connection unavailable.")

        self.bot._playback_sessions[ctx.guild.id] = self.bot._playback_sessions.get(ctx.guild.id, 0) + 1

        self.bot._cancel_monitor(ctx.guild.id)
        self.bot._cancel_predownload(ctx.guild.id)

        self.bot._start_stream(ctx.guild.id, ctx.voice_client)

        track = await self.bot.engine.play_track(state)
        if not track:
            return await self._finish_playback(ctx, state, "Failed to play track.")

        await self._after_track_started(ctx, state)
        self._install_monitor(ctx, state)

    async def _after_track_started(self, ctx: commands.Context, state: PlaybackState) -> None:
        await self._send_now_playing(ctx, state)
        if ctx.guild:
            self.bot._schedule_predownload(ctx.guild.id, state)

    def _voice_member_count(self, ctx: commands.Context) -> int:
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.channel:
            return 0
        members = getattr(voice_client.channel, "members", [])
        return sum(1 for member in members if not getattr(member, "bot", False))

    def _install_monitor(self, ctx: commands.Context, state: PlaybackState) -> None:
        if not ctx.guild:
            return
        guild_id = ctx.guild.id

        async def on_track_end(s: PlaybackState) -> None:
            next_t = await self.bot.engine.skip_track(s)
            if next_t:
                await self._after_track_started(ctx, s)
            else:
                await self._finish_playback(ctx, s, "Playlist ended.")

        async def on_empty() -> None:
            await self.bot.engine.stop(state)
            self.bot._stop_stream(ctx.guild.id)
            self.bot._cancel_predownload(ctx.guild.id)
            self.bot.release_lease(ctx.guild.id)
            if ctx.voice_client:
                await ctx.voice_client.disconnect()

        def get_voice_members() -> int:
            return self._voice_member_count(ctx)

        async def run_monitor() -> None:
            try:
                await self.bot.monitor.monitor_loop(state, on_track_end, on_empty, get_voice_members)
            finally:
                current = self.bot._monitor_tasks.get(guild_id)
                if current is asyncio.current_task():
                    self.bot._monitor_tasks.pop(guild_id, None)

        self.bot._monitor_tasks[guild_id] = asyncio.create_task(run_monitor())

    async def _send_now_playing(self, ctx: commands.Context, state: PlaybackState) -> None:
        # Dedup: skip if same track+position was sent in the last 5 seconds
        key = (state.current_track, state.position)
        now = time.time()
        if key == (self._last_sent[0], self._last_sent[1]) and now - self._last_sent[2] < 5:
            return
        self._last_sent = (state.current_track, state.position, now)

        collection_id = state.current_collection_id or state.collection_mode
        col = get_collection(collection_id)
        meta = self.bot.engine.get_track_metadata(state.current_track, collection_id)
        title = self.bot.engine.audio.current_song()
        if not title:
            title = meta.get("NAME", "") or ""
        if not title:
            title = state.current_track.rsplit("/", 1)[-1]
        author = meta.get("AUTHOR", "")
        embed = now_playing_embed(
            title=title,
            author=author,
            collection_name=col.name if col else collection_id,
            collection_icon=col.icon if col else "?",
            position=state.position + 1,
            total=len(state.queue),
            color=col.color if col else 0x00FF00,
        )
        msg = await ctx.send(embed=discord.Embed.from_dict(embed))
        if msg is None:
            return
        self.bot._track_np_message(msg.id, {
            "filepath": state.current_track,
            "collection_id": collection_id,
        })
        await msg.add_reaction(FAVORITE_EMOJI)
