"""Playback command cog."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING

from .cog_shared import FAVORITE_EMOJI, PlaybackCtx
from .collection_loader import get_collection, load_raw_paths
from .discord_compat import commands, discord
from .embeds import now_playing_embed, queue_embed
from .models import PlaybackState
from .remote import is_remote_track

if TYPE_CHECKING:
    from .bot import ObibokBot

logger = logging.getLogger(__name__)

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
                continue
            if not self.bot.try_acquire_lease(guild):
                continue
            self._last_auto_start = time.time()
            try:
                track = await self.bot.engine.start_radio(state, user_id=members[0].id)
                if not track:
                    self.bot.release_lease(guild.id)
                    continue

                await self._connect_and_play(
                    PlaybackCtx(guild, members[0], None, None),
                    state,
                    channel,
                    failure_prefix="Auto-reconnect failed",
                )
                logger.info("Auto-reconnect: resumed playback for %d users in %s", len(members), channel.name)
            except Exception as exc:
                logger.warning("Auto-reconnect failed: %s", exc)
                self.bot.release_lease(guild.id)

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

    async def _connect_and_play(
        self,
        ctx: commands.Context,
        state: PlaybackState,
        voice_channel,
        *,
        start_message: str = "",
        failure_prefix: str,
    ) -> None:
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            ctx.voice_client = await voice_channel.connect()
            state.voice_channel_id = voice_channel.id
            if start_message:
                await ctx.send(start_message)
            await self._play_and_monitor(ctx, state)
        except Exception as exc:
            await self._finish_playback(ctx, state, f"{failure_prefix}: {exc}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        # Handle bot's own voice reconnect — restart stream if we were playing.
        if self.bot.user and member.bot and member.id == self.bot.user.id:
            logger.debug("Bot voice state: %s → %s", before.channel, after.channel)
            if after.channel is not None and before.channel is None:
                guild_id = member.guild.id
                state = self.bot.get_state(guild_id)
                if state.is_playing:
                    logger.info("Bot reconnected to voice, restarting stream")
                    vc = member.guild.voice_client
                    if vc and vc.is_connected():
                        self.bot._start_stream(guild_id, vc)
                        self._install_monitor(self._get_fallback_ctx(member, vc), state)
            return

        # Handle bot's own voice reconnect — restart stream if we were playing
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
        try:
            track = await self.bot.engine.start_radio(state, user_id=member.id)
            if not track:
                self.bot.release_lease(member.guild.id)
                return
            ctx = PlaybackCtx(member.guild, member, None, after.channel.send)
            await self._connect_and_play(ctx, state, after.channel, failure_prefix="Auto-start failed")
        except Exception as exc:
            await self.bot.engine.stop(state)
            self.bot._stop_stream(member.guild.id)
            self.bot._cancel_predownload(member.guild.id)
            self.bot._cancel_monitor(member.guild.id)
            self.bot.release_lease(member.guild.id)
            logger.warning("Auto-start failed: %s", exc)

    def _get_fallback_ctx(self, member: discord.Member, vc) -> PlaybackCtx:
        """Build a fallback context for stream restart after bot voice reconnect."""
        return PlaybackCtx(member.guild, member, vc, None)

    async def _ensure_voice(self, ctx: commands.Context):
        """Return user's voice channel, or None after sending an error message."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Join a voice channel first!")
            return None
        return ctx.author.voice.channel

    def _load_collection(self, state: PlaybackState) -> None:
        """Load track list for the current collection if not already cached."""
        if not state.tracks:
            paths = load_raw_paths(state.collection_mode, self.bot.root_dir)
            if paths:
                state.tracks = paths

    @commands.command(aliases=["pl", "radio", "start"])
    async def play(self, ctx: commands.Context, *, query: str = "") -> None:
        if not ctx.guild:
            return
        voice_channel = await self._ensure_voice(ctx)
        if not voice_channel:
            return

        state = self.bot.get_state(ctx.guild.id)

        if is_remote_track(query):
            if not self.bot.try_acquire_lease(ctx.guild):
                owner = self.bot.playback_lease.owner_guild_name or "another server"
                return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
            self.bot._cancel_predownload(ctx.guild.id)
            self._set_queue(state, [(query, state.collection_mode)])
            await self._connect_and_play(
                ctx, state, voice_channel,
                start_message="Starting remote track...",
                failure_prefix="Failed to play remote track",
            )
            return

        if query.isdigit():
            idx = int(query) - 1
            if not state.search_results or idx < 0 or idx >= len(state.search_results):
                return await ctx.send("Invalid number. Use !search first.")
            path = state.search_results[idx]
            if not self.bot.try_acquire_lease(ctx.guild):
                owner = self.bot.playback_lease.owner_guild_name or "another server"
                return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
            from .audio import _is_sap_supported
            supported, reason = _is_sap_supported(path)
            if not supported:
                return await ctx.send(f"⛔ Can't play `{path.rsplit('/', 1)[-1]}` — {reason}.")
            self.bot._cancel_predownload(ctx.guild.id)
            self._set_queue(state, [(path, state.search_collection_id or state.collection_mode)])
            await self._connect_and_play(
                ctx, state, voice_channel,
                failure_prefix="Failed to play selection",
            )
            return

        if query:
            self._load_collection(state)
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
            await self._connect_and_play(
                ctx, state, voice_channel,
                start_message=f"Starting search result for `{query}`...",
                failure_prefix="Failed to play search result",
            )
            return

        if ctx.voice_client:
            await ctx.voice_client.disconnect()

        if not self.bot.try_acquire_lease(ctx.guild):
            owner = self.bot.playback_lease.owner_guild_name or "another server"
            return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
        try:
            self.bot._cancel_predownload(ctx.guild.id)
            track = await self.bot.engine.start_radio(state, user_id=ctx.author.id)
            if not track:
                self.bot.release_lease(ctx.guild.id)
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                return await ctx.send("No tracks in this collection. Run `make build-indexes` first.")
            await self._connect_and_play(
                ctx, state, voice_channel,
                start_message=f"Starting **{state.collection_mode.upper()}** radio...",
                failure_prefix="Failed to start playback",
            )
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
        await self._send_now_playing(ctx, state, skip_dedup=True)

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
        # Use the guild's actual voice client (ctx.voice_client can be stale after reconnect)
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_connected():
            # Try getting fresh voice client from the guild
            if ctx.guild:
                voice_client = ctx.guild.voice_client
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

    async def _send_now_playing(self, ctx: commands.Context, state: PlaybackState, *, skip_dedup: bool = False) -> None:
        if not skip_dedup:
            # Dedup: skip if same track+position was sent in the last 5 seconds
            key = (state.current_track, state.position)
            now = time.time()
            if key == (self._last_sent[0], self._last_sent[1]) and now - self._last_sent[2] < 5:
                return
            self._last_sent = (state.current_track, state.position, now)

        collection_id = state.current_collection_id or state.collection_mode
        col = get_collection(collection_id)
        meta = self.bot.engine.get_track_metadata(state.current_track, collection_id)
        title = await self.bot.engine.audio.async_current_song()
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
