from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse

import discord
from discord.ext import commands

from moosicbot.config import Settings
from moosicbot.local_audio import LocalAudioLibrary
from moosicbot.models import TrackRequest
from moosicbot.player import PlayerRegistry
from moosicbot.sources import SourceResolver
from moosicbot.youtube import YouTubeAudioService


def _duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _split_query_and_position(value: str) -> tuple[str, int | None]:
    query = value.strip()
    head, separator, tail = query.rpartition(" ")
    if separator and tail.isdigit():
        return head.strip(), int(tail)
    return query, None


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings
        self.resolver = SourceResolver(settings.ytdlp_default_search)
        self.local_audio = LocalAudioLibrary(settings.local_music_dir)
        self.youtube = YouTubeAudioService(self.local_audio, settings.ytdlp_default_search)
        self.players = PlayerRegistry(bot, self.resolver, settings.default_volume, settings.ffmpeg_executable)

    def cog_unload(self) -> None:
        self.bot.loop.create_task(self.players.disconnect_all())

    async def _guard(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            await ctx.reply("Use this inside a server so I can join a voice channel.", mention_author=False)
            return False
        if self.settings.allowed_discord_user_ids and ctx.author.id not in self.settings.allowed_discord_user_ids:
            await ctx.reply("This bot is locked to its configured Discord user allow-list.", mention_author=False)
            return False
        return True

    async def _ensure_voice(self, ctx: commands.Context) -> discord.VoiceClient | None:
        if not isinstance(ctx.author, discord.Member):
            await ctx.reply("I could not see your voice channel.", mention_author=False)
            return None

        voice_state = ctx.author.voice
        if not voice_state or not voice_state.channel:
            await ctx.reply("Join a voice channel first, then try again.", mention_author=False)
            return None

        channel = voice_state.channel
        voice_client = ctx.guild.voice_client if ctx.guild else None
        if voice_client and voice_client.channel != channel:
            await voice_client.move_to(channel)
        elif not voice_client:
            voice_client = await channel.connect(timeout=15, reconnect=True)
        return voice_client

    async def _enqueue(
        self,
        ctx: commands.Context,
        tracks: Iterable[TrackRequest],
        position: int | None = None,
    ) -> int:
        track_list = list(tracks)
        if not track_list or ctx.guild is None:
            return 0
        player = self.players.for_guild(ctx.guild.id)
        return player.enqueue(track_list, ctx.channel, position)

    async def _queue_query(
        self,
        ctx: commands.Context,
        query: str,
        position: int | None = None,
    ) -> None:
        if not await self._ensure_voice(ctx):
            return

        local_track = None if _looks_like_url(query) else self.local_audio.find(query)
        if local_track:
            request = self.local_audio.to_request(local_track, ctx.author.display_name)
            queued_position = await self._enqueue(ctx, [request], position)
            if position is None:
                await ctx.reply(f"Queued saved track **{local_track.title}**.", mention_author=False)
            else:
                await ctx.reply(f"Inserted saved track **{local_track.title}** at queue position {queued_position}.", mention_author=False)
            return

        await ctx.reply("Downloading audio...", mention_author=False)
        async with ctx.typing():
            try:
                track = await self.youtube.download(query)
            except Exception as exc:
                await ctx.reply(f"I could not download that audio: `{exc}`", mention_author=False)
                return

        request = self.local_audio.to_request(track, ctx.author.display_name)
        queued_position = await self._enqueue(ctx, [request], position)
        if position is None:
            await ctx.reply(f"Downloaded and queued **{track.title}**.", mention_author=False)
        else:
            await ctx.reply(f"Downloaded and inserted **{track.title}** at queue position {queued_position}.", mention_author=False)

    @commands.command(name="help", aliases=["commands"])
    async def help_command(self, ctx: commands.Context) -> None:
        prefix = self.settings.command_prefix
        lines = [
            "**MoosicBot Commands**",
            "",
            "**Play And Queue**",
            f"`{prefix}play <song or URL>` - Play a saved match first; otherwise download from YouTube and queue it.",
            f"`{prefix}queue` - Show the current song and upcoming songs.",
            f"`{prefix}queue <song or URL> [position]` - Queue or insert audio. Use position `1` to play it next.",
            f"`{prefix}nowplaying` - Show the current song.",
            "",
            "**Playback Controls**",
            f"`{prefix}volume [0-100]` - Show or set playback volume.",
            f"`{prefix}pause` - Pause the current song.",
            f"`{prefix}resume` - Resume paused playback.",
            f"`{prefix}skip` - Skip the current song.",
            f"`{prefix}stop` - Stop playback and clear the queue.",
            f"`{prefix}join` - Join your voice channel.",
            f"`{prefix}disconnect` - Leave voice and clear the queue.",
            "",
            "**YouTube**",
            f"`{prefix}youtube_search <search>` - Show YouTube results without downloading.",
            f"`{prefix}youtube_download <song or URL>` - Download audio into the library without queueing it.",
            "",
            "**Local Library**",
            f"`{prefix}local_upload [title]` - Attach an audio file and save it locally.",
            f"`{prefix}local_remove <name>` - Remove a saved audio file.",
            f"`{prefix}local_list` - Show saved local songs.",
        ]
        await ctx.reply("\n".join(lines), mention_author=False)

    @commands.command(name="youtube_search", aliases=["ytsearch", "search"])
    async def youtube_search(self, ctx: commands.Context, *, query: str) -> None:
        if not await self._guard(ctx):
            return

        async with ctx.typing():
            try:
                limit = max(1, self.settings.youtube_search_limit)
                results = await self.youtube.search(query, limit)
            except Exception as exc:
                await ctx.reply(f"I could not search YouTube: `{exc}`", mention_author=False)
                return

        if not results:
            await ctx.reply("No YouTube results found.", mention_author=False)
            return

        lines = []
        for index, result in enumerate(results, start=1):
            duration = _duration(result.duration)
            uploader = f" - {result.uploader}" if result.uploader else ""
            suffix = f" ({duration})" if duration else ""
            lines.append(f"{index}. **{result.title}**{suffix}{uploader}\n{result.url}")
        await ctx.reply("\n\n".join(lines), mention_author=False)

    @commands.command(name="youtube_download", aliases=["ytdl", "download"])
    async def youtube_download(self, ctx: commands.Context, *, query: str) -> None:
        if not await self._guard(ctx):
            return

        await ctx.reply("Downloading audio...", mention_author=False)
        async with ctx.typing():
            try:
                track = await self.youtube.download(query)
            except Exception as exc:
                await ctx.reply(f"I could not download that audio: `{exc}`", mention_author=False)
                return

        await ctx.reply(
            f"Downloaded **{track.title}** to `{track.path.name}` ({track.display_size}).",
            mention_author=False,
        )

    @commands.command(name="local_upload", aliases=["upload"])
    async def local_upload(self, ctx: commands.Context, *, title: str = "") -> None:
        if not await self._guard(ctx):
            return
        if not ctx.message.attachments:
            await ctx.reply("Attach an audio file to the message, then run this command.", mention_author=False)
            return

        attachment = ctx.message.attachments[0]
        async with ctx.typing():
            try:
                track = await self.local_audio.save_attachment(attachment, title or None)
            except ValueError as exc:
                await ctx.reply(str(exc), mention_author=False)
                return

        await ctx.reply(
            f"Stored **{track.title}** as `{track.path.name}` ({track.display_size}).",
            mention_author=False,
        )

    @commands.command(name="local_list", aliases=["library", "songs"])
    async def local_list(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return

        tracks = self.local_audio.tracks()
        if not tracks:
            await ctx.reply("The local music library is empty.", mention_author=False)
            return

        lines = [
            f"{index}. {track.title} (`{track.path.suffix.lstrip('.')}`, {track.display_size})"
            for index, track in enumerate(tracks[:20], start=1)
        ]
        if len(tracks) > 20:
            lines.append(f"...and {len(tracks) - 20} more.")
        await ctx.reply("\n".join(lines), mention_author=False)

    @commands.command(name="local_remove", aliases=["remove", "delete"])
    async def local_remove(self, ctx: commands.Context, *, name: str) -> None:
        if not await self._guard(ctx):
            return

        track = self.local_audio.find(name)
        if not track:
            await ctx.reply("I could not find a local track matching that name.", mention_author=False)
            return

        try:
            self.local_audio.remove(track)
        except ValueError as exc:
            await ctx.reply(str(exc), mention_author=False)
            return

        await ctx.reply(f"Removed **{track.title}** from the local music library.", mention_author=False)

    @commands.command(name="join")
    async def join(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return
        voice = await self._ensure_voice(ctx)
        if voice:
            await ctx.reply(f"Joined **{voice.channel.name}**.", mention_author=False)

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        if not await self._guard(ctx):
            return
        await self._queue_query(ctx, query)

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx: commands.Context, level: int | None = None) -> None:
        if not await self._guard(ctx):
            return
        if ctx.guild is None:
            return

        player = self.players.for_guild(ctx.guild.id)
        if level is None:
            await ctx.reply(f"Volume is currently {round(player.volume * 100)}%.", mention_author=False)
            return
        if level < 0 or level > 100:
            await ctx.reply("Volume must be between 0 and 100.", mention_author=False)
            return

        player.set_volume(level / 100)
        await ctx.reply(f"Volume set to {level}%.", mention_author=False)

    @commands.command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return
        voice = ctx.guild.voice_client if ctx.guild else None
        if voice and voice.is_playing():
            voice.pause()
            await ctx.reply("Paused.", mention_author=False)
        else:
            await ctx.reply("Nothing is playing.", mention_author=False)

    @commands.command(name="resume")
    async def resume(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return
        voice = ctx.guild.voice_client if ctx.guild else None
        if voice and voice.is_paused():
            voice.resume()
            await ctx.reply("Resumed.", mention_author=False)
        else:
            await ctx.reply("Nothing is paused.", mention_author=False)

    @commands.command(name="skip")
    async def skip(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return
        player = self.players.for_guild(ctx.guild.id) if ctx.guild else None
        if player and player.skip():
            await ctx.reply("Skipped.", mention_author=False)
        else:
            await ctx.reply("Nothing is playing.", mention_author=False)

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return
        player = self.players.for_guild(ctx.guild.id) if ctx.guild else None
        if player:
            player.stop()
        await ctx.reply("Stopped and cleared the queue.", mention_author=False)

    @commands.command(name="disconnect", aliases=["leave"])
    async def disconnect(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return
        player = self.players.for_guild(ctx.guild.id) if ctx.guild else None
        if player:
            await player.disconnect()
        await ctx.reply("Disconnected.", mention_author=False)

    @commands.command(name="queue", aliases=["q"])
    async def queue(self, ctx: commands.Context, *, query: str = "") -> None:
        if not await self._guard(ctx):
            return
        if query:
            song_query, position = _split_query_and_position(query)
            if not song_query:
                await ctx.reply("Tell me which song to queue.", mention_author=False)
                return
            await self._queue_query(ctx, song_query, position)
            return

        player = self.players.for_guild(ctx.guild.id) if ctx.guild else None
        if not player or (not player.now_playing and not player.queue):
            await ctx.reply("The queue is empty.", mention_author=False)
            return

        lines: list[str] = []
        if player.now_resolved:
            duration = _duration(player.now_resolved.duration)
            lines.append(f"Now: **{player.now_resolved.title}** {duration}".strip())
        elif player.now_playing:
            lines.append(f"Now: **{player.now_playing.title}**")

        for index, track in enumerate(list(player.queue)[:10], start=1):
            duration = _duration(track.duration)
            lines.append(f"{index}. {track.title} {duration}".strip())

        if len(player.queue) > 10:
            lines.append(f"...and {len(player.queue) - 10} more.")
        await ctx.reply("\n".join(lines), mention_author=False)

    @commands.command(name="nowplaying", aliases=["np"])
    async def nowplaying(self, ctx: commands.Context) -> None:
        if not await self._guard(ctx):
            return
        player = self.players.for_guild(ctx.guild.id) if ctx.guild else None
        if not player or not player.now_playing:
            await ctx.reply("Nothing is playing.", mention_author=False)
            return

        resolved = player.now_resolved
        if resolved:
            duration = _duration(resolved.duration)
            await ctx.reply(f"Now playing: **{resolved.title}** {duration}".strip(), mention_author=False)
        else:
            await ctx.reply(f"Resolving: **{player.now_playing.title}**", mention_author=False)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"Missing `{error.param.name}`. Try `{self.settings.command_prefix}help`.", mention_author=False)
            return
        if isinstance(error, commands.BadArgument):
            await ctx.reply(f"Bad argument: `{error}`", mention_author=False)
            return
        raise error
