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
from .favorites import PlaylistLibrary
from .lease import PlaybackLease
from .models import PlaybackState
from .monitor import TrackMonitor
from .playback import PlaybackEngine
from .remote import is_remote_track
from .stream import MonitorAudioSource

logger = logging.getLogger(__name__)


class ObibokBot(commands.Bot):
    def __init__(
        self,
        engine: PlaybackEngine,
        monitor: TrackMonitor,
        root_dir: str,
        sink_name: str = "robbo_bot",
        command_prefix: str = "!",
        guild_id: int | None = None,
        auto_start_channel: str = "",
        default_loop: bool = False,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.reactions = True
        # NOTE: members intent requires manual enable in Discord Developer Portal
        # intents.members = True
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.engine = engine
        self.monitor = monitor
        self.root_dir = root_dir
        self.sink_name = sink_name
        self.guild_id = guild_id
        self.auto_start_channel = auto_start_channel
        self.default_loop = default_loop
        self.playback_lease = PlaybackLease()
        self._states: dict[int, PlaybackState] = {}
        self._np_messages: dict[int, dict] = {}
        self._monitor_tasks: dict[int, asyncio.Task] = {}
        self._predownload_tasks: dict[int, asyncio.Task] = {}
        self._active_streams: dict[int, MonitorAudioSource] = {}
        self._background_tasks: list[asyncio.Task] = []
        self._np_messages_max = 200
        self._reaction_users: dict[tuple[int, int], set[str]] = {}

    def _track_np_message(self, msg_id: int, data: dict[str, Any]) -> None:
        if len(self._np_messages) >= self._np_messages_max:
            oldest = next(iter(self._np_messages))
            del self._np_messages[oldest]
        self._np_messages[msg_id] = data

    def _start_stream(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        """Start or restart the MonitorAudioSource on the given voice client."""
        old = self._active_streams.pop(guild_id, None)
        if old:
            if hasattr(old, "cleanup"):
                old.cleanup()
        source = MonitorAudioSource(sink_name=self.sink_name)
        source.source_id = id(source)
        voice_client.play(
            source,
            after=lambda e: self._on_stream_end(guild_id, e, source.source_id),
        )
        self._active_streams[guild_id] = source

    def _stop_stream(self, guild_id: int) -> None:
        source = self._active_streams.pop(guild_id, None)
        if source and hasattr(source, "cleanup"):
            source.cleanup()

    def _on_stream_end(self, guild_id: int, error: Exception | None, source_id: int) -> None:
        if error:
            logger.warning("Stream ended with error for guild %s: %s", guild_id, error)
        current = self._active_streams.get(guild_id)
        if current is not None and getattr(current, "source_id", None) == source_id:
            self._active_streams.pop(guild_id, None)

    def try_acquire_lease(self, guild: discord.Guild) -> bool:
        return self.playback_lease.acquire(guild.id, guild.name)

    def release_lease(self, guild_id: int | None = None) -> None:
        if guild_id is None or self.playback_lease.owner_guild_id == guild_id:
            self.playback_lease.release()

    def _cancel_predownload(self, guild_id: int) -> None:
        task = self._predownload_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _cancel_monitor(self, guild_id: int) -> None:
        task = self._monitor_tasks.pop(guild_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _schedule_predownload(self, guild_id: int, state: PlaybackState) -> None:
        self._cancel_predownload(guild_id)
        task = asyncio.create_task(self.engine.predownload_next(state))
        self._predownload_tasks[guild_id] = task

    def get_state(self, guild_id: int) -> PlaybackState:
        if guild_id not in self._states:
            self._states[guild_id] = PlaybackState(guild_id=guild_id, is_looping=self.default_loop)
        return self._states[guild_id]

    async def process_commands(self, message: discord.Message) -> None:
        if self.guild_id is not None and message.guild and message.guild.id != self.guild_id:
            return
        await super().process_commands(message)

    async def setup_hook(self) -> None:
        # Remove default help command before registering custom one
        self.remove_command("help")
        await self.add_cog(PlaybackCog(self))
        await self.add_cog(CollectionCog(self))
        await self.add_cog(FavoritesCog(self))
        await self.add_cog(ToolsCog(self))
        self._background_tasks.append(asyncio.create_task(self._health_watchdog()))

    async def close(self) -> None:
        for task in self._background_tasks:
            task.cancel()
        for task in self._background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Background task failed during shutdown: %s", exc)
        self._background_tasks.clear()
        for guild_id in list(self._active_streams):
            self._stop_stream(guild_id)
        for task in list(self._predownload_tasks.values()):
            task.cancel()
        self._predownload_tasks.clear()
        for task in list(self._monitor_tasks.values()):
            task.cancel()
        self._monitor_tasks.clear()
        await super().close()

    async def _health_watchdog(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(self.engine.audio.ensure_ready)
            except Exception as exc:
                logger.warning("Health watchdog failed: %s", exc)


class PlaybackCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot = bot

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
        if before.channel is not None:
            return
        if after.channel is None:
            return
        if after.channel.name != self.bot.auto_start_channel:
            return
        state = self.bot.get_state(member.guild.id)
        if state.is_playing:
            return
        if not self.bot.try_acquire_lease(member.guild):
            return
        vc = None
        try:
            vc = await after.channel.connect()
            track = self.bot.engine.start_radio(state, user_id=member.id)
            if not track:
                self.bot.release_lease(member.guild.id)
                await vc.disconnect()
                return
            state.voice_channel_id = after.channel.id

            class FakeCtx:
                def __init__(self, guild, author, voice_client, send_fn):
                    self.guild = guild
                    self.author = author
                    self.voice_client = voice_client
                    self._send = send_fn

                async def send(self, *args, **kwargs):
                    return await self._send(*args, **kwargs)

            async def noop_send(*args, **kwargs):
                return None

            send_fn = member.guild.system_channel.send if member.guild.system_channel else noop_send
            ctx = FakeCtx(member.guild, member, vc, send_fn)
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
            state.queue = [query]
            state.queue_collection_ids = [state.collection_mode]
            state.position = 0
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
            state.queue = [path]
            state.queue_collection_ids = [state.search_collection_id or state.collection_mode]
            state.position = 0
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
            state.queue = list(results)
            state.queue_collection_ids = [state.collection_mode] * len(state.queue)
            state.position = 0
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
            track = self.bot.engine.start_radio(state, user_id=ctx.author.id)
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
        title = meta.get("NAME", state.current_track.rsplit("/", 1)[-1])
        author = meta.get("AUTHOR", "Unknown")
        embed = now_playing_embed(
            title=title,
            author=author,
            collection_name=col.name if col else collection_id,
            collection_icon=col.icon if col else "?",
            position=state.position + 1,
            total=len(state.queue),
        )
        msg = await ctx.send(embed=discord.Embed.from_dict(embed))
        self.bot._track_np_message(msg.id, {
            "filepath": state.current_track,
            "collection_id": collection_id,
        })

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
        self.bot._cancel_monitor(ctx.guild.id)
        self.bot._cancel_predownload(ctx.guild.id)
        track = await self.bot.engine.jump_to_track(state, index - 1)
        if not track:
            return await ctx.send("Invalid position.")
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
            return await ctx.send(f"Volume: {vol}%" if vol else "Volume: unknown")
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
        if not ctx.voice_client:
            return await self._finish_playback(ctx, state, "Voice connection unavailable.")

        self.bot._cancel_monitor(ctx.guild.id)
        self.bot._cancel_predownload(ctx.guild.id)

        # Start audio stream (restart if needed — handles voice reconnects)
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
            return 1

        async def run_monitor() -> None:
            try:
                await self.bot.monitor.monitor_loop(state, on_track_end, on_empty, get_voice_members)
            finally:
                current = self.bot._monitor_tasks.get(guild_id)
                if current is asyncio.current_task():
                    self.bot._monitor_tasks.pop(guild_id, None)

        self.bot._monitor_tasks[guild_id] = asyncio.create_task(run_monitor())

    async def _send_now_playing(self, ctx: commands.Context, state: PlaybackState) -> None:
        collection_id = state.current_collection_id or state.collection_mode
        meta = self.bot.engine.get_track_metadata(state.current_track, collection_id)
        col = get_collection(collection_id)
        title = meta.get("NAME", state.current_track.rsplit("/", 1)[-1])
        author = meta.get("AUTHOR", "")
        embed = now_playing_embed(
            title=title,
            author=author,
            collection_name=col.name if col else collection_id,
            collection_icon=col.icon if col else "?",
            position=state.position + 1,
            total=len(state.queue),
        )
        msg = await ctx.send(embed=discord.Embed.from_dict(embed))
        self.bot._track_np_message(msg.id, {
            "filepath": state.current_track,
            "collection_id": collection_id,
        })


class CollectionCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
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
        state.search_results = []
        state.search_collection_id = ""
        col = get_collection(collection_id)
        await ctx.send(f"{col.flip_tag} **Switched to {col.name}**" if col else f"Switched to {collection_id}")
        if not active:
            return
        try:
            await ctx.author.voice.channel.connect()
            state.voice_channel_id = ctx.author.voice.channel.id
            track = self.bot.engine.start_radio(state, collection_id=collection_id, user_id=ctx.author.id)
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


class FavoritesCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot = bot

    def _reaction_key(self, msg_id: int, user_id: int) -> tuple[int, int]:
        return (msg_id, user_id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id:
            return
        msg_data = self.bot._np_messages.get(payload.message_id)
        if not msg_data:
            return
        key = self._reaction_key(payload.message_id, payload.user_id)
        emojis = self.bot._reaction_users.setdefault(key, set())
        was_empty = len(emojis) == 0
        emojis.add(str(payload.emoji))
        if was_empty:
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
        key = self._reaction_key(payload.message_id, payload.user_id)
        emojis = self.bot._reaction_users.get(key, set())
        emojis.discard(str(payload.emoji))
        if not emojis:
            self.bot._reaction_users.pop(key, None)
            self.bot.engine.toggle_favorite(
                payload.user_id,
                msg_data["filepath"],
                msg_data["collection_id"],
            )

    @commands.command(aliases=["favs"])
    async def favorites(self, ctx: commands.Context) -> None:
        tracks = self.bot.engine.favorites.get_tracks(ctx.author.id)
        if not tracks:
            return await ctx.send("📭 **No favorites yet.** React to a Now Playing embed with any emoji to save tracks here!")
        lines = [f"🎵 **Your Favorites ({len(tracks)} tracks)**"]
        for i, t in enumerate(tracks, 1):
            name = t.get("title", t["filepath"].rsplit("/", 1)[-1])
            author_s = f" — {t['author']}" if t.get("author") else ""
            lines.append(f"`{i}.` {name}{author_s}")
        for chunk_start in range(0, len(lines), 15):
            await ctx.send("\n".join(lines[chunk_start:chunk_start + 15]))

    @commands.command(aliases=["fp"])
    async def favplay(self, ctx: commands.Context, *, number: str = "") -> None:
        if not ctx.guild or not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Join a voice channel first!")
        tracks = self.bot.engine.favorites.get_tracks(ctx.author.id)
        if not tracks:
            return await ctx.send("📭 **No favorites yet.** React to any Now Playing embed with an emoji to save tracks!")
        if number:
            try:
                idx = int(number) - 1
                if idx < 0 or idx >= len(tracks):
                    return await ctx.send(f"Number must be between 1 and {len(tracks)}.")
                filtered = [tracks[idx]]
            except ValueError:
                return await ctx.send("Usage: `!favplay <number>` or `!favplay` to play all.")
        else:
            bl_tracks = self.bot.engine.blacklist.get_tracks(ctx.author.id)
            filtered = [t for t in tracks if t["filepath"] not in bl_tracks]
            import random
            random.shuffle(filtered)
        if not filtered:
            return await ctx.send("⛔ All favorites are blacklisted. Nothing to play!")
        if not self.bot.try_acquire_lease(ctx.guild):
            owner = self.bot.playback_lease.owner_guild_name or "another server"
            return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
        state = self.bot.get_state(ctx.guild.id)
        queued = [
            (track["filepath"], track.get("collection_id") or state.collection_mode)
            for track in filtered
        ]
        state.queue = [filepath for filepath, _ in queued]
        state.queue_collection_ids = [collection_id for _, collection_id in queued]
        state.position = 0
        state.is_looping = True
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            await ctx.author.voice.channel.connect()
            state.voice_channel_id = ctx.author.voice.channel.id
            await ctx.send(f"🎵 **Playing {len(filtered)} favorites!**")
            cog = self.bot.get_cog("PlaybackCog")
            if cog:
                await cog._play_and_monitor(ctx, state)
        except Exception as exc:
            cog = self.bot.get_cog("PlaybackCog")
            if cog:
                await cog._finish_playback(ctx, state, f"Failed to play favorites: {exc}")
            else:
                self.bot.release_lease(ctx.guild.id)
                await ctx.send(f"Failed to play favorites: {exc}")

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

    @commands.command(aliases=["pls"])
    async def favsave(self, ctx: commands.Context, *, name: str) -> None:
        tracks = self.bot.engine.favorites.get_tracks(ctx.author.id)
        if not tracks:
            return await ctx.send("No favorites to save.")
        lib = PlaylistLibrary(self.bot.root_dir)
        lib.save(name, tracks, ctx.author.id, ctx.author.name)
        await ctx.send(f"Saved as `{name}` ({len(tracks)} tracks).")

    @commands.command(aliases=["fpl"])
    async def favload(self, ctx: commands.Context, *, name: str) -> None:
        if name.strip().lower() == "list":
            lib = PlaylistLibrary(self.bot.root_dir)
            playlists = lib.list_playlists()
            if not playlists:
                return await ctx.send("📂 **No playlists saved yet.** Use `!favsave <name>` to create one!")
            lines = ["📂 **Saved Playlists**"]
            for p in playlists:
                author_s = f" by {p['author']}" if p['author'] != "?" else ""
                lines.append(f"`{p['name']}` — {p['tracks']} tracks{author_s}")
            return await ctx.send("\n".join(lines))
        if not ctx.guild or not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Join a voice channel first!")
        lib = PlaylistLibrary(self.bot.root_dir)
        playlist = lib.load(name)
        if not playlist:
            return await ctx.send(f"Playlist `{name}` not found.")
        if not self.bot.try_acquire_lease(ctx.guild):
            owner = self.bot.playback_lease.owner_guild_name or "another server"
            return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
        state = self.bot.get_state(ctx.guild.id)
        queued = [
            (track["filepath"], track.get("collection_id") or state.collection_mode)
            for track in playlist.get("tracks", [])
        ]
        import random
        random.shuffle(queued)
        state.queue = [filepath for filepath, _ in queued]
        state.queue_collection_ids = [collection_id for _, collection_id in queued]
        state.position = 0
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            await ctx.author.voice.channel.connect()
            state.voice_channel_id = ctx.author.voice.channel.id
            await ctx.send(f"🎵 **Playing playlist `{playlist.get('name', name)}`!**")
            cog = self.bot.get_cog("PlaybackCog")
            if cog:
                await cog._play_and_monitor(ctx, state)
        except Exception as exc:
            cog = self.bot.get_cog("PlaybackCog")
            if cog:
                await cog._finish_playback(ctx, state, f"Failed to load playlist: {exc}")
            else:
                self.bot.release_lease(ctx.guild.id)
                await ctx.send(f"Failed to load playlist: {exc}")

    @commands.command(aliases=["plist"])
    async def playlists(self, ctx: commands.Context) -> None:
        lib = PlaylistLibrary(self.bot.root_dir)
        playlists = lib.list_playlists()
        if not playlists:
            return await ctx.send("No saved playlists.")
        lines = [f"`{p['name']}` — {p['tracks']} tracks by {p['author']}" for p in playlists]
        await ctx.send("\n".join(lines))


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
