from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    allowed_discord_user_ids: set[int]
    command_prefix: str
    default_volume: float
    ffmpeg_executable: str | None
    local_music_dir: Path
    youtube_search_limit: int
    ytdlp_default_search: str


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


def _int_set(name: str) -> set[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    return {int(part.strip()) for part in raw.split(",") if part.strip()}


def _float_between(name: str, default: float, low: float, high: float) -> float:
    raw = os.getenv(name, "").strip()
    value = float(raw) if raw else default
    return max(low, min(high, value))


def load_settings() -> Settings:
    load_dotenv()

    discord_token = os.getenv("DISCORD_TOKEN", "").strip()
    if not discord_token:
        raise RuntimeError("DISCORD_TOKEN is required. Copy .env.example to .env and fill it in.")

    local_music_dir = Path(os.getenv("LOCAL_MUSIC_DIR", "local_music")).expanduser()
    local_music_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        discord_token=discord_token,
        discord_guild_id=_optional_int("DISCORD_GUILD_ID"),
        allowed_discord_user_ids=_int_set("ALLOWED_DISCORD_USER_IDS"),
        command_prefix=os.getenv("COMMAND_PREFIX", "!").strip() or "!",
        default_volume=_float_between("DEFAULT_VOLUME", 0.55, 0.0, 1.0),
        ffmpeg_executable=os.getenv("FFMPEG_EXECUTABLE", "").strip() or None,
        local_music_dir=local_music_dir,
        youtube_search_limit=int(os.getenv("YOUTUBE_SEARCH_LIMIT", "5")),
        ytdlp_default_search=os.getenv("YTDLP_DEFAULT_SEARCH", "ytsearch").strip() or "ytsearch",
    )
