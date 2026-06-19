from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import discord

from moosicbot.models import TrackRequest


ALLOWED_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".webm"}
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(slots=True, frozen=True)
class LocalTrack:
    title: str
    path: Path
    size_bytes: int

    @property
    def display_size(self) -> str:
        size_mb = self.size_bytes / (1024 * 1024)
        return f"{size_mb:.1f} MB"


class LocalAudioLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def tracks(self) -> list[LocalTrack]:
        tracks: list[LocalTrack] = []
        for path in self.root.iterdir():
            if path.is_file() and path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS:
                tracks.append(LocalTrack(title=path.stem, path=path, size_bytes=path.stat().st_size))
        return sorted(tracks, key=lambda track: track.title.casefold())

    def find(self, query: str) -> LocalTrack | None:
        normalized = query.casefold().strip()
        tracks = self.tracks()
        for track in tracks:
            if normalized in {track.title.casefold(), track.path.name.casefold()}:
                return track
        for track in tracks:
            if normalized in track.title.casefold() or normalized in track.path.name.casefold():
                return track
        return None

    def track_from_path(self, path: Path) -> LocalTrack:
        if path.suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError(f"Unsupported audio file type: {path.suffix}")
        return LocalTrack(title=path.stem, path=path, size_bytes=path.stat().st_size)

    async def save_attachment(self, attachment: discord.Attachment, title: str | None = None) -> LocalTrack:
        extension = Path(attachment.filename).suffix.lower()
        if extension not in ALLOWED_AUDIO_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
            raise ValueError(f"Unsupported audio file type. Allowed extensions: {allowed}")

        stem = self.safe_stem(title or Path(attachment.filename).stem)
        path = self.unique_path(stem, extension)
        await attachment.save(str(path))
        return LocalTrack(title=path.stem, path=path, size_bytes=path.stat().st_size)

    def remove(self, track: LocalTrack) -> None:
        resolved_root = self.root.resolve()
        resolved_path = track.path.resolve()
        if resolved_root not in resolved_path.parents:
            raise ValueError("Refusing to remove a file outside the local music library.")
        resolved_path.unlink()

    @staticmethod
    def to_request(track: LocalTrack, requested_by: str) -> TrackRequest:
        return TrackRequest(
            title=track.title,
            query=track.title,
            requested_by=requested_by,
            file_path=str(track.path),
        )

    def unique_path(self, stem: str, extension: str) -> Path:
        path = self.root / f"{stem}{extension}"
        index = 2
        while path.exists():
            path = self.root / f"{stem}-{index}{extension}"
            index += 1
        return path

    @staticmethod
    def safe_stem(value: str) -> str:
        cleaned = SAFE_NAME_RE.sub("_", value).strip(" ._-")
        return cleaned[:80] or "track"
