"""Favorites, blacklist, and playlist cogs."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from .cog_shared import FAVORITE_EMOJI
from .collection_loader import resolve_collection_for_filepath
from .favorites import PlaylistLibrary

if TYPE_CHECKING:
    from .bot import ObibokBot


class FavoritesCog(commands.Cog):
    def __init__(self, bot: ObibokBot) -> None:
        self.bot: ObibokBot = bot
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != FAVORITE_EMOJI:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        msg_data = self.bot._np_messages.get(payload.message_id)
        if not msg_data:
            return
        # Resolve collection from filepath (only for unambiguous extensions)
        filepath = msg_data["filepath"]
        ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
        if ext in ("sid", "sap", "ay", "ym"):
            resolved_col = resolve_collection_for_filepath(filepath)
            collection_id = resolved_col or msg_data["collection_id"]
        else:
            collection_id = msg_data["collection_id"] or resolve_collection_for_filepath(filepath) or ""
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
            msg_data["collection_id"],
        )

    @commands.command(aliases=["favs"])
    async def favorites(self, ctx: commands.Context) -> None:
        logger = logging.getLogger(__name__)
        tracks = self.bot.engine.favorites.get_tracks(ctx.author.id)
        logger.info("!favs called by %s — %d tracks in cache", ctx.author.id, len(tracks))
        if not tracks:
            return await ctx.send("📭 **No favorites yet.** React to a Now Playing embed with any emoji to save tracks here!")
        lines = [f"🎵 **Your Favorites ({len(tracks)} tracks)**"]
        bad_titles_seen = 0
        for i, t in enumerate(tracks, 1):
            name = t.get("title", "")
            # Strip non-printable chars (binary metadata prefixes: SID/SAP headers, etc.)
            if name:
                name = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name).strip()
            # Fix old "downloads" titles from ModArchive URLs
            if not name or name == "downloads":
                filepath = t["filepath"]
                bad_titles_seen += 1
                if "downloads.php?moduleid=" in filepath:
                    mod_id = filepath.split("moduleid=", 1)[-1].split("&", 1)[0]
                    name = f"ModArchive #{mod_id}"
                else:
                    # Try to fetch real metadata
                    meta = self.bot.engine.get_track_metadata(filepath, t.get("collection_id", ""))
                    name = meta.get("NAME", "")
                    # Also strip nulls from fetched metadata
                    if name:
                        name = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name).strip()
            if not name:
                fallback = t["filepath"].rsplit("/", 1)[-1]
                # Remove extension for cleaner display
                fallback = fallback.rsplit(".", 1)[0].replace("_", " ")
                name = fallback
            author_s = f" — {t['author']}" if t.get("author") else ""
            lines.append(f"`{i}.` {name}{author_s}")
        if bad_titles_seen:
            logger.info("!favs: repaired %d bad titles", bad_titles_seen)
        first = True
        for chunk_start in range(0, len(lines), 15):
            if not first:
                await asyncio.sleep(1.5)
            await ctx.send("\n".join(lines[chunk_start:chunk_start + 15]))
            first = False

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
        queued = []
        for track in filtered:
            filepath = track["filepath"]
            saved_cid = track.get("collection_id")
            ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
            # Unambiguous extensions: sid/sap/ay/ym — resolve from filepath
            # Ambiguous (mod/xm/s3m/it): trust saved collection_id
            if ext in ("sid", "sap", "ay", "ym"):
                cid = resolve_collection_for_filepath(filepath) or saved_cid or state.collection_mode
            else:
                cid = saved_cid or resolve_collection_for_filepath(filepath) or state.collection_mode
            queued.append((filepath, cid))
        playback_cog = self.bot.get_cog("PlaybackCog")
        if playback_cog:
            playback_cog._set_queue(state, queued, shuffle=True)
        state.is_looping = True
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                await asyncio.sleep(0.5)  # let Discord clean up old session
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
        queued = []
        for track in playlist.get("tracks", []):
            filepath = track["filepath"]
            saved_cid = track.get("collection_id")
            ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
            if ext in ("sid", "sap", "ay", "ym"):
                cid = resolve_collection_for_filepath(filepath) or saved_cid or state.collection_mode
            else:
                cid = saved_cid or resolve_collection_for_filepath(filepath) or state.collection_mode
            queued.append((filepath, cid))
        playback_cog = self.bot.get_cog("PlaybackCog")
        if playback_cog:
            playback_cog._set_queue(state, queued, shuffle=True)
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                await asyncio.sleep(0.5)  # let Discord clean up old session
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
