from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_LYRICS_API_BASE = "https://lrclib.net/api"
DEFAULT_TIMEOUT_SECONDS = 10.0
USER_AGENT = "MoosicBot/1.0"

NOISE_RE = re.compile(
    r"\s*[\[(](?:official\s+)?(?:music\s+)?(?:video|audio|lyrics?|lyric\s+video|visualizer)[\])]",
    re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(r"^\s*(?:\[[0-9:.]+\]\s*)+")
YOUTUBE_ID_SUFFIX_RE = re.compile(r"\s+\[[A-Za-z0-9_-]{6,}\]\s*$")
WORD_RE = re.compile(r"[a-z0-9]+")


class LyricsLookupError(RuntimeError):
    """Raised when the lyrics provider cannot be reached or returns bad data."""


class LyricsNotFound(RuntimeError):
    """Raised when no matching lyrics are available."""


@dataclass(slots=True, frozen=True)
class LyricsResult:
    track_name: str
    artist_name: str | None
    album_name: str | None
    duration: float | None
    lyrics: str
    instrumental: bool
    provider: str = "LRCLIB"

    @property
    def display_title(self) -> str:
        if self.artist_name:
            return f"{self.track_name} - {self.artist_name}"
        return self.track_name


UrlOpener = Callable[[Request, float], Any]


def clean_lyrics_query(value: str) -> str:
    cleaned = YOUTUBE_ID_SUFFIX_RE.sub("", value).strip()
    cleaned = NOISE_RE.sub("", cleaned).strip(" -_")
    return re.sub(r"\s+", " ", cleaned)


def strip_synced_timestamps(value: str) -> str:
    lines = [TIMESTAMP_RE.sub("", line).rstrip() for line in value.splitlines()]
    return "\n".join(lines).strip()


class LyricsService:
    def __init__(
        self,
        api_base: str = DEFAULT_LYRICS_API_BASE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        opener: UrlOpener | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self._opener = opener or (lambda request, timeout: urlopen(request, timeout=timeout))

    async def search(self, query: str, duration: int | float | None = None) -> LyricsResult:
        return await asyncio.to_thread(self._search_sync, query, duration)

    def _search_sync(self, query: str, duration: int | float | None = None) -> LyricsResult:
        cleaned_query = clean_lyrics_query(query)
        if not cleaned_query:
            raise LyricsNotFound("empty lyrics query")

        data = self._get_json("search", {"q": cleaned_query})
        if not isinstance(data, list):
            raise LyricsLookupError("lyrics provider returned an unexpected response")

        result = self._choose_result(data, cleaned_query, float(duration) if duration else None)
        if not result:
            raise LyricsNotFound(cleaned_query)
        return result

    def _get_json(self, endpoint: str, params: dict[str, str]) -> Any:
        url = f"{self.api_base}/{endpoint}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Lrclib-Client": USER_AGENT,
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self._opener(request, self.timeout) as response:
                payload = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise LyricsNotFound from exc
            raise LyricsLookupError(f"lyrics provider returned HTTP {exc.code}") from exc
        except (OSError, TimeoutError, URLError) as exc:
            raise LyricsLookupError(str(exc)) from exc

        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LyricsLookupError("lyrics provider returned invalid JSON") from exc

    def _choose_result(
        self,
        items: list[Any],
        query: str,
        duration: float | None,
    ) -> LyricsResult | None:
        candidates = [self._result_from_item(item) for item in items if isinstance(item, dict)]
        candidates = [candidate for candidate in candidates if candidate]
        if not candidates:
            return None
        return max(candidates, key=lambda candidate: self._score(candidate, query, duration))

    @staticmethod
    def _result_from_item(item: dict[str, Any]) -> LyricsResult | None:
        plain_lyrics = _string(item.get("plainLyrics"))
        synced_lyrics = _string(item.get("syncedLyrics"))
        lyrics = plain_lyrics or (strip_synced_timestamps(synced_lyrics) if synced_lyrics else "")
        instrumental = bool(item.get("instrumental"))
        if not lyrics and not instrumental:
            return None

        track_name = _string(item.get("trackName")) or _string(item.get("name")) or "Unknown Track"
        return LyricsResult(
            track_name=track_name,
            artist_name=_string(item.get("artistName")),
            album_name=_string(item.get("albumName")),
            duration=_float_or_none(item.get("duration")),
            lyrics=lyrics,
            instrumental=instrumental,
        )

    @staticmethod
    def _score(result: LyricsResult, query: str, duration: float | None) -> float:
        query_words = set(WORD_RE.findall(query.casefold()))
        candidate_words = set(WORD_RE.findall(result.display_title.casefold()))
        score = 0.0

        if query_words and candidate_words:
            score += 10.0 * len(query_words & candidate_words) / len(query_words | candidate_words)

        normalized_query = " ".join(sorted(query_words))
        normalized_candidate = " ".join(sorted(candidate_words))
        if normalized_query and normalized_query == normalized_candidate:
            score += 10.0

        if result.lyrics:
            score += 3.0
        if result.instrumental:
            score += 1.0
        if duration is not None and result.duration is not None:
            delta = abs(duration - result.duration)
            score += max(0.0, 5.0 - min(delta, 30.0) / 6.0)
        return score


def _string(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
