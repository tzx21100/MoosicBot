from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import yt_dlp

from moosicbot.local_audio import LocalAudioLibrary, LocalTrack


@dataclass(slots=True, frozen=True)
class YouTubeResult:
    title: str
    url: str
    duration: int | None
    uploader: str | None


class YouTubeAudioService:
    def __init__(self, library: LocalAudioLibrary, default_search: str) -> None:
        self.library = library
        self.default_search = default_search

    async def search(self, query: str, limit: int) -> list[YouTubeResult]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    async def download(self, query: str, title: str | None = None) -> LocalTrack:
        return await asyncio.to_thread(self._download_sync, query, title)

    def _search_sync(self, query: str, limit: int) -> list[YouTubeResult]:
        options = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

        results: list[YouTubeResult] = []
        for entry in info.get("entries", []) if info else []:
            if not entry:
                continue
            results.append(
                YouTubeResult(
                    title=entry.get("title") or "Untitled",
                    url=self._entry_url(entry),
                    duration=entry.get("duration"),
                    uploader=entry.get("uploader") or entry.get("channel"),
                )
            )
        return results

    def _download_sync(self, query: str, title: str | None = None) -> LocalTrack:
        value = query if self._looks_like_url(query) else f"ytsearch1:{query}"
        options = {
            "format": "bestaudio/best",
            "outtmpl": str(self.library.root / "%(title).80s [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,
            "source_address": "0.0.0.0",
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(value, download=True)
            entry = self._first_entry(info)
            path = self._downloaded_path(ydl, entry)

        if title:
            path = self._rename(path, title)
        return self.library.track_from_path(path)

    def _downloaded_path(self, ydl: yt_dlp.YoutubeDL, entry: dict[str, Any]) -> Path:
        for download in entry.get("requested_downloads") or []:
            filepath = download.get("filepath")
            if filepath:
                return Path(filepath)

        filename = Path(ydl.prepare_filename(entry))
        if filename.exists():
            return filename

        video_id = entry.get("id")
        matches = sorted(
            (path for path in self.library.root.iterdir() if path.is_file() and video_id and video_id in path.stem),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]

        raise RuntimeError("yt-dlp finished without reporting the downloaded file path.")

    def _rename(self, path: Path, title: str) -> Path:
        target = self.library.unique_path(self.library.safe_stem(title), path.suffix)
        path.rename(target)
        return target

    @staticmethod
    def _entry_url(entry: dict[str, Any]) -> str:
        if entry.get("webpage_url"):
            return entry["webpage_url"]
        if entry.get("url") and str(entry["url"]).startswith("http"):
            return entry["url"]
        video_id = entry.get("id") or entry.get("url")
        return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def _first_entry(info: dict[str, Any]) -> dict[str, Any]:
        entries = info.get("entries")
        if entries:
            first = next((entry for entry in entries if entry), None)
            if first:
                return first
        return info

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
