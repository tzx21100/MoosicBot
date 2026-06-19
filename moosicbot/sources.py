from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yt_dlp

from moosicbot.models import ResolvedTrack, TrackRequest


class SourceResolver:
    def __init__(self, default_search: str) -> None:
        self._ydl_options: dict[str, Any] = {
            "format": "bestaudio/best",
            "default_search": default_search,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "source_address": "0.0.0.0",
        }

    async def resolve(self, request: TrackRequest) -> ResolvedTrack:
        if request.file_path:
            path = Path(request.file_path)
            if not path.is_file():
                raise RuntimeError(f"Local audio file is missing: {path.name}")
            return ResolvedTrack(
                title=request.title,
                stream_url=str(path),
                webpage_url=None,
                duration=request.duration,
            )

        info = await self._extract(request.source_url or request.query)
        entry = self._first_entry(info)
        stream_url = entry.get("url")
        if not stream_url:
            raise RuntimeError(f"Could not find a playable audio stream for {request.title!r}.")

        return ResolvedTrack(
            title=entry.get("title") or request.title,
            stream_url=stream_url,
            webpage_url=entry.get("webpage_url") or request.webpage_url,
            duration=entry.get("duration") or request.duration,
        )

    async def build_request(self, query: str, requested_by: str) -> TrackRequest:
        info = await self._extract(query)
        entry = self._first_entry(info)
        title = entry.get("title") or query
        return TrackRequest(
            title=title,
            query=query,
            requested_by=requested_by,
            source_url=entry.get("webpage_url") or query,
            webpage_url=entry.get("webpage_url"),
            duration=entry.get("duration"),
        )

    async def _extract(self, value: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._extract_sync, value)

    def _extract_sync(self, value: str) -> dict[str, Any]:
        with yt_dlp.YoutubeDL(self._ydl_options) as ydl:
            return ydl.extract_info(value, download=False)

    @staticmethod
    def _first_entry(info: dict[str, Any]) -> dict[str, Any]:
        entries = info.get("entries")
        if entries:
            first = next((entry for entry in entries if entry), None)
            if first:
                return first
        return info
