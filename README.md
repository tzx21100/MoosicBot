# MoosicBot

A Discord music bot that searches YouTube, downloads audio into a local library, and plays that local audio in a Discord voice channel.

Use it only for audio you own, created, or otherwise have permission to download and play.

## Features

- `!play` searches the local library first, then downloads from YouTube if no saved track matches.
- `!youtube_search` shows YouTube search results and URLs.
- `!youtube_download` downloads YouTube audio into the local library without joining voice.
- `!local_upload`, `!local_list`, and `!local_remove` manage stored audio files.
- `!queue` shows the current queue, and `!queue <song name or YouTube search> [position]` queues or inserts audio.
- `!volume` shows or sets playback volume.
- Prefix commands for join, pause, resume, skip, stop, disconnect, queue, and now playing.
- Per-server queue with one active player per guild.
- Optional Discord user allow-list.

## Requirements

- Python 3.11 or newer.
- FFmpeg installed and available on your `PATH`, set with `FFMPEG_EXECUTABLE`, or provided by `imageio-ffmpeg` from `requirements.txt`.
- A Discord bot token from the Discord Developer Portal.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill in `.env`.

For Discord, invite the bot with these scopes:

```text
bot
```

The bot needs these permissions:

```text
View Channels, Send Messages, Read Message History, Connect, Speak, Use Voice Activity
```

In the Discord Developer Portal, open your bot and enable:

```text
Privileged Gateway Intents -> Message Content Intent
```

Set `DISCORD_GUILD_ID` to your test server ID if you want the bot to clear old guild slash commands on startup. Prefix commands work immediately once the bot is online.

## Run

```powershell
python bot.py
```

Downloaded files are stored under `LOCAL_MUSIC_DIR`, which defaults to `local_music`.

If playback says FFmpeg is missing, reinstall dependencies or set an explicit path in `.env`:

```env
FFMPEG_EXECUTABLE=C:\path\to\ffmpeg.exe
```

## Commands

```text
!help
!play song name, youtube url, or search terms
!queue
!queue song name
!queue song name queue-position
!nowplaying
!volume
!volume 0-100
!pause
!resume
!skip
!stop
!join
!disconnect
!youtube_search search terms
!youtube_download youtube url or search terms
!local_upload optional title
!local_remove name
!local_list
```

## Notes

`!play` never streams directly from YouTube. It first looks for a saved local match. If none exists, it downloads the selected audio, stores it locally, then queues the saved file.

Use `!queue iris` to append a local match or download a new match. Use `!queue iris 1` to make it play next.

Keep `ALLOWED_DISCORD_USER_IDS` set if you only want certain Discord users to download and queue audio.
