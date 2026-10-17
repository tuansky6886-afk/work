"""Fetch a YouTube video's caption track (song lyrics, when the video has them).

Uses the public timed-text captions. No download, no Whisper model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {
    "youtu.be",
    "youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
}
_PATH_MARKERS = ("embed", "shorts", "live", "v", "clip")


class TranscriptError(Exception):
    """A failure we can show to the user as-is."""


@dataclass(frozen=True)
class CaptionTrack:
    language: str
    language_code: str
    is_generated: bool

    @property
    def label(self) -> str:
        kind = "auto-generated" if self.is_generated else "manual"
        return f"{self.language} ({self.language_code}) · {kind}"


@dataclass(frozen=True)
class TranscriptResult:
    video_id: str
    title: str
    track: CaptionTrack
    snippets: tuple[tuple[float, str], ...]
    tracks: tuple[CaptionTrack, ...]


def extract_video_id(value: str) -> str:
    """Accept a watch URL, youtu.be, Shorts, embed, or a bare 11-character id."""
    raw = value.strip()
    if not raw:
        raise TranscriptError("Paste a YouTube link first.")
    if _VIDEO_ID_RE.fullmatch(raw):
        return raw

    candidate = raw if "://" in raw else "https://" + raw
    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    if host not in _YOUTUBE_HOSTS and not host.endswith(".youtube.com"):
        raise TranscriptError("That doesn't look like a YouTube link.")

    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            video_id = query_id
        else:
            parts = [part for part in parsed.path.split("/") if part]
            for marker in _PATH_MARKERS:
                if marker in parts:
                    index = parts.index(marker)
                    if index + 1 < len(parts):
                        video_id = parts[index + 1]
                    break

    video_id = video_id.strip()
    if not _VIDEO_ID_RE.fullmatch(video_id):
        raise TranscriptError("Couldn't find a video id in that link.")
    return video_id


def fetch_youtube_transcript(url: str, language_code: str | None = None, generated: bool | None = None) -> TranscriptResult:
    """List caption tracks and fetch one of them.

    With no language, prefer a manually uploaded track (usually the original
    lyrics) and fall back to the first auto-generated track.
    """
    video_id = extract_video_id(url)
    try:
        listing = YouTubeTranscriptApi().list(video_id)
    except TranscriptsDisabled as exc:
        raise TranscriptError("Captions are turned off for this video.") from exc
    except (VideoUnavailable, VideoUnplayable) as exc:
        raise TranscriptError("This video is unavailable. It may be private, deleted, or blocked.") from exc
    except AgeRestricted as exc:
        raise TranscriptError("This video is age-restricted, so its captions can't be read.") from exc
    except (RequestBlocked, IpBlocked, PoTokenRequired) as exc:
        raise TranscriptError("YouTube blocked the caption request. Wait a moment and try again.") from exc
    except CouldNotRetrieveTranscript as exc:
        raise TranscriptError(f"Couldn't reach YouTube captions.\n\n{exc}") from exc

    tracks = tuple(
        CaptionTrack(language=item.language, language_code=item.language_code, is_generated=item.is_generated)
        for item in listing
    )
    if not tracks:
        raise TranscriptError("This video has no captions.")

    track = _select_track(tracks, language_code, generated)
    try:
        if track.is_generated:
            transcript = listing.find_generated_transcript([track.language_code])
        else:
            transcript = listing.find_manually_created_transcript([track.language_code])
        fetched = transcript.fetch()
    except NoTranscriptFound as exc:
        raise TranscriptError(f"No captions were found for {track.label}.") from exc
    except CouldNotRetrieveTranscript as exc:
        raise TranscriptError(f"Couldn't download that caption track.\n\n{exc}") from exc

    snippets = tuple((float(snippet.start), snippet.text) for snippet in fetched)
    if not any(text.strip() for _start, text in snippets):
        raise TranscriptError("The caption track was empty.")

    return TranscriptResult(
        video_id=video_id,
        title=_video_title(video_id),
        track=track,
        snippets=snippets,
        tracks=tracks,
    )


def format_transcript(snippets: tuple[tuple[float, str], ...] | list[tuple[float, str]], with_timestamps: bool) -> str:
    """Turn caption cues into copyable text, one cue per block."""
    blocks: list[str] = []
    for start, text in snippets:
        lines = _clean_lines(text)
        if not lines:
            continue
        body = "\n".join(lines)
        if with_timestamps:
            blocks.append(f"[{_format_timestamp(start)}] {body}")
        else:
            blocks.append(body)
    if not blocks:
        return ""
    return "\n".join(blocks)


def _select_track(tracks: tuple[CaptionTrack, ...], language_code: str | None, generated: bool | None) -> CaptionTrack:
    if language_code:
        for track in tracks:
            if track.language_code == language_code and (generated is None or track.is_generated == generated):
                return track
        for track in tracks:
            if track.language_code == language_code:
                return track
    manual = [track for track in tracks if not track.is_generated]
    if manual:
        return manual[0]
    return tracks[0]


def _video_title(video_id: str) -> str:
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=15,
        )
        if response.ok:
            title = response.json().get("title")
            if isinstance(title, str):
                return title.strip()
    except requests.RequestException:
        return ""
    return ""


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.replace("\r", "").split("\n"):
        collapsed = " ".join(line.split())
        if collapsed:
            lines.append(collapsed)
    return lines


def _format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
