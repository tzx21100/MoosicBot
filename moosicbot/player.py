from __future__ import annotations

import asyncio
from collections import deque
import contextlib
import logging
from pathlib import Path
import shutil

import discord

from moosicbot.models import ResolvedTrack, TrackRequest
from moosicbot.sources import SourceResolver


FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn -loglevel warning"
LOCAL_FFMPEG_BEFORE_OPTIONS = None


def is_local_file(value: str) -> bool:
    try:
        return Path(value).is_file()
    except OSError:
        return False


def resolve_ffmpeg_executable(configured: str | None = None) -> str:
    if configured:
        return configured

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError(
            "FFmpeg was not found on PATH. Install FFmpeg, set FFMPEG_EXECUTABLE, "
            "or reinstall requirements so imageio-ffmpeg is available."
        ) from exc

    return imageio_ffmpeg.get_ffmpeg_exe()


class GuildPlayer:
    def __init__(
        self,
        bot: discord.Client,
        guild_id: int,
        resolver: SourceResolver,
        volume: float,
        ffmpeg_executable: str,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.resolver = resolver
        self.volume = volume
        self.ffmpeg_executable = ffmpeg_executable
        self.queue: deque[TrackRequest] = deque()
        self.now_playing: TrackRequest | None = None
        self.now_resolved: ResolvedTrack | None = None
        self.text_channel: discord.abc.Messageable | None = None
        self._next_event = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None

    def enqueue(
        self,
        tracks: list[TrackRequest],
        text_channel: discord.abc.Messageable | None,
        position: int | None = None,
    ) -> int:
        insert_index = len(self.queue)
        if position is None:
            self.queue.extend(tracks)
        else:
            insert_index = max(0, min(position - 1, len(self.queue)))
            for offset, track in enumerate(tracks):
                self.queue.insert(insert_index + offset, track)
        if text_channel:
            self.text_channel = text_channel
        if not self._runner or self._runner.done():
            self._runner = asyncio.create_task(self._play_loop(), name=f"guild-player-{self.guild_id}")
        return insert_index + 1

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        voice = self.voice_client
        if voice and isinstance(voice.source, discord.PCMVolumeTransformer):
            voice.source.volume = self.volume

    def skip(self) -> bool:
        voice = self.voice_client
        if not voice or not voice.is_playing():
            return False
        voice.stop()
        return True

    def stop(self) -> None:
        self.queue.clear()
        voice = self.voice_client
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()

    async def disconnect(self) -> None:
        self.stop()
        if self._runner:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
        voice = self.voice_client
        if voice and voice.is_connected():
            await voice.disconnect(force=True)

    @property
    def voice_client(self) -> discord.VoiceClient | None:
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return None
        return guild.voice_client

    async def _play_loop(self) -> None:
        while True:
            if not self.queue:
                self.now_playing = None
                self.now_resolved = None
                return

            request = self.queue.popleft()
            self.now_playing = request
            self.now_resolved = None

            voice = self.voice_client
            if not voice or not voice.is_connected():
                await self._announce(f"Skipped **{request.title}** because I am not connected to a voice channel.")
                continue

            self._next_event.clear()
            try:
                resolved = await self.resolver.resolve(request)
                self.now_resolved = resolved
                before_options = LOCAL_FFMPEG_BEFORE_OPTIONS if is_local_file(resolved.stream_url) else FFMPEG_BEFORE_OPTIONS
                source = discord.FFmpegPCMAudio(
                    resolved.stream_url,
                    executable=self.ffmpeg_executable,
                    before_options=before_options,
                    options=FFMPEG_OPTIONS,
                )
                audio = discord.PCMVolumeTransformer(source, volume=self.volume)
                voice.play(audio, after=self._after_track)
            except Exception as exc:
                logging.exception("Failed to resolve or start %s", request.title)
                await self._announce(f"Could not play **{request.title}**: `{exc}`. I skipped it.")
                continue

            await self._announce(f"Now playing: **{resolved.title}**")
            await self._next_event.wait()

    def _after_track(self, error: Exception | None) -> None:
        if error:
            logging.warning("Discord voice playback error in guild %s: %s", self.guild_id, error)
        self.bot.loop.call_soon_threadsafe(self._next_event.set)

    async def _announce(self, message: str) -> None:
        if not self.text_channel:
            return
        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            await self.text_channel.send(message)


class PlayerRegistry:
    def __init__(
        self,
        bot: discord.Client,
        resolver: SourceResolver,
        volume: float,
        ffmpeg_executable: str | None = None,
    ) -> None:
        self.bot = bot
        self.resolver = resolver
        self.volume = volume
        self.ffmpeg_executable = resolve_ffmpeg_executable(ffmpeg_executable)
        self._players: dict[int, GuildPlayer] = {}

    def for_guild(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if not player:
            player = GuildPlayer(self.bot, guild_id, self.resolver, self.volume, self.ffmpeg_executable)
            self._players[guild_id] = player
        return player

    async def disconnect_all(self) -> None:
        await asyncio.gather(*(player.disconnect() for player in self._players.values()), return_exceptions=True)
