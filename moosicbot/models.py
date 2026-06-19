from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TrackRequest:
    title: str
    query: str
    requested_by: str
    source_url: str | None = None
    webpage_url: str | None = None
    file_path: str | None = None
    duration: int | None = None

    @property
    def label(self) -> str:
        if self.webpage_url:
            return f"[{self.title}]({self.webpage_url})"
        return self.title


@dataclass(slots=True)
class ResolvedTrack:
    title: str
    stream_url: str
    webpage_url: str | None
    duration: int | None
