"""Favorites, blacklist, and playlist cogs."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import TYPE_CHECKING

from .cog_shared import FAVORITE_EMOJI
from .collection_loader import resolve_collection_for_saved_track
from .discord_compat import commands, discord
from .favorites import PlaylistLibrary

if TYPE_CHECKING:
    from .bot import ObibokBot

class FavoritesCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot: ObibokBot = bot

    def _build_queued_tracks(
        self,
        tracks: list[dict],
        fallback_collection_id: str,
    ) -> list[tuple[str, str]]:
        queued: list[tuple[str, str]] = []
        for track in tracks:
            filepath = track["filepath"]
            cid = resolve_collection_for_saved_track(
                filepath,
                track.get("collection_id", ""),
                fallback_collection_id,
            )
            queued.append((filepath, cid))
        return queued

    async def _play_queued_tracks(
        self,
        ctx: commands.Context,
        state,
        queued: list[tuple[str, str]],
        *,
        success_message: str,
        failure_prefix: str,
    ) -> None:
        playback_cog = self.bot.get_cog("PlaybackCog")
        if playback_cog:
            playback_cog._set_queue(state, queued, shuffle=True)
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            await ctx.author.voice.channel.connect()
            state.voice_channel_id = ctx.author.voice.channel.id
            await ctx.send(success_message)
            if playback_cog:
                await playback_cog._play_and_monitor(ctx, state)
        except Exception as exc:
            if playback_cog:
                await playback_cog._finish_playback(ctx, state, f"{failure_prefix}: {exc}")
            else:
                self.bot.release_lease(ctx.guild.id)
                await ctx.send(f"{failure_prefix}: {exc}")
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != FAVORITE_EMOJI:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        msg_data = self.bot._np_messages.get(payload.message_id)
        if not msg_data:
            return
        filepath = msg_data["filepath"]
        collection_id = resolve_collection_for_saved_track(
            filepath,
            msg_data["collection_id"],
            "",
        )
        meta = self.bot.engine.get_track_metadata(msg_data["filepath"], collection_id)
        raw_title = meta.get("NAME", "") or ""
        # Strip non-printable chars from metadata (SID/SAP headers often contain binary prefixes)
        if raw_title:
            raw_title = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', raw_title).strip()
        if not raw_title:
            filepath = msg_data["filepath"]
            # ModArchive download URLs have no real filename — extract module ID
            if "downloads.php?moduleid=" in filepath:
                mod_id = filepath.split("moduleid=", 1)[-1].split("&", 1)[0]
                raw_title = f"ModArchive #{mod_id}"
            else:
                raw_title = filepath.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ")
        self.bot.engine.favorites.add(
            payload.user_id,
            msg_data['filepath'],
            raw_title,
            collection_id,
            meta.get("AUTHOR", "") or "",
        )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != FAVORITE_EMOJI:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        msg_data = self.bot._np_messages.get(payload.message_id)
        if not msg_data:
            return
        self.bot.engine.favorites.remove(
            payload.user_id,
            msg_data["filepath"],
        )

    @commands.command(aliases=["favs"])
    async def favorites(self, ctx: commands.Context) -> None:
        logger = logging.getLogger(__name__)
        tracks = self.bot.engine.favorites.get_tracks(ctx.author.id)
        logger.info("!favs called by %s — %d tracks in cache", ctx.author.id, len(tracks))
        if not tracks:
            return await ctx.send("📭 **No favorites yet.** React to a Now Playing embed with any emoji to save tracks here!")
        lines = [f"🎵 **Your Favorites ({len(tracks)} tracks)**"]
        _clean_re = re.compile(r'[\x00-\x1f\x7f-\x9f]')
        bad_titles_fixed = 0
        for i, t in enumerate(tracks, 1):
            name = t.get("title", "")
            if name:
                name = _clean_re.sub('', name).strip()
            # Repair tracks that have missing or placeholder titles
            # (download.php URLs stored without proper metadata, etc.)
            if not name or name.lower() in ("downloads", "download", "untitled", "unknown", "tmp"):
                filepath = t["filepath"]
                if "downloads.php?moduleid=" in filepath:
                    mod_id = filepath.split("moduleid=", 1)[-1].split("&", 1)[0]
                    name = f"ModArchive #{mod_id}"
                else:
                    meta = await asyncio.to_thread(
                        self.bot.engine.get_track_metadata, filepath, t.get("collection_id", "")
                    )
                    name = meta.get("NAME", "")
                    if name:
                        name = _clean_re.sub('', name).strip()
                    if name:
                        self.bot.engine.favorites.set_track_metadata(
                            ctx.author.id, t["filepath"], name, meta.get("AUTHOR", "")
                        )
                if name:
                    bad_titles_fixed += 1
            if not name:
                fallback = t["filepath"].rsplit("/", 1)[-1]
                fallback = fallback.rsplit(".", 1)[0].replace("_", " ")
                name = fallback
                bad_titles_fixed += 1
            author_s = f" — {t.get('author', '')}" if t.get("author") else ""
            lines.append(f"`{i}.` {name}{author_s}")
        if bad_titles_fixed:
            logger.info("!favs: repaired %d bad titles", bad_titles_fixed)
        for i, chunk_start in enumerate(range(0, len(lines), 15)):
            if i > 0:
                await asyncio.sleep(0.5)
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
            random.shuffle(filtered)
        if not filtered:
            return await ctx.send("⛔ All favorites are blacklisted. Nothing to play!")
        if not self.bot.try_acquire_lease(ctx.guild):
            owner = self.bot.playback_lease.owner_guild_name or "another server"
            return await ctx.send(f"🔊 Music is already playing in **{owner}**.")
        state = self.bot.get_state(ctx.guild.id)
        state.is_looping = True
        queued = self._build_queued_tracks(filtered, state.collection_mode)
        await self._play_queued_tracks(
            ctx,
            state,
            queued,
            success_message=f"🎵 **Playing {len(filtered)} favorites!**",
            failure_prefix="Failed to play favorites",
        )

    @commands.command()
    async def blk(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        state = self.bot.get_state(ctx.guild.id)
        if self.bot.engine.blacklist_current(ctx.author.id, state):
            await ctx.send("Blacklisted.")
        else:
            await ctx.send("Nothing to blacklist.")

    @commands.command(aliases=["blklist"])
    async def blks(self, ctx: commands.Context) -> None:
        tracks = self.bot.engine.blacklist.get_tracks(ctx.author.id)
        if not tracks:
            return await ctx.send("📭 **No blacklisted tracks.** Use `!blk` on a playing track to add it here.")
        lines = [f"⛔ **Your Blacklist ({len(tracks)} tracks)**"]
        for i, t in enumerate(tracks, 1):
            name = t.rsplit("/", 1)[-1] if "/" in t else t
            lines.append(f"`{i}.` {name}")
        for chunk_start in range(0, len(lines), 15):
            await ctx.send("\n".join(lines[chunk_start:chunk_start + 15]))

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
        queued = self._build_queued_tracks(playlist.get("tracks", []), state.collection_mode)
        await self._play_queued_tracks(
            ctx,
            state,
            queued,
            success_message=f"🎵 **Playing playlist `{playlist.get('name', name)}`!**",
            failure_prefix="Failed to load playlist",
        )

    @commands.command(aliases=["plist"])
    async def playlists(self, ctx: commands.Context) -> None:
        lib = PlaylistLibrary(self.bot.root_dir)
        playlists = lib.list_playlists()
        if not playlists:
            return await ctx.send("No saved playlists.")
        lines = [f"`{p['name']}` — {p['tracks']} tracks by {p['author']}" for p in playlists]
        await ctx.send("\n".join(lines))
