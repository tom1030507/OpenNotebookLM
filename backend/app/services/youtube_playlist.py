"""Bounded YouTube playlist expansion for source ingestion."""
from itertools import islice
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlsplit


MAX_YOUTUBE_PLAYLIST_VIDEOS = 50


def is_youtube_url(url: str) -> bool:
    """Return whether a URL points to YouTube or its short-link host.

    Args:
        url: Candidate source URL.

    Returns:
        True for a YouTube video or playlist host.
    """
    hostname = (urlsplit(url).hostname or "").lower()
    return hostname in {
        "youtu.be",
        "www.youtu.be",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }


def is_youtube_playlist_url(url: str) -> bool:
    """Return whether a YouTube URL carries playlist semantics.

    Args:
        url: Candidate YouTube URL.

    Returns:
        True for a playlist page or a video URL with a playlist id.
    """
    parsed = urlsplit(url)
    if not is_youtube_url(url):
        return False
    return parsed.path.rstrip("/") == "/playlist" or bool(
        parse_qs(parsed.query).get("list")
    )


def _default_youtube_dl_factory(options: Dict[str, Any]) -> Any:
    """Build yt-dlp lazily so ordinary application startup does not load it.

    Args:
        options: yt-dlp options for playlist-only extraction.

    Returns:
        Configured yt-dlp downloader.
    """
    import yt_dlp

    return yt_dlp.YoutubeDL(options)


def expand_youtube_playlist(
    url: str,
    youtube_dl_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Tuple[List[Dict[str, Optional[str]]], bool]:
    """Resolve at most 50 flat video entries from a YouTube URL.

    Args:
        url: Public YouTube playlist or video URL already validated by the caller.
        youtube_dl_factory: Optional yt-dlp factory for controlled tests.

    Returns:
        Video URLs and titles, plus whether the playlist exceeded the cap.
    """
    factory = youtube_dl_factory or _default_youtube_dl_factory
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "playlistend": MAX_YOUTUBE_PLAYLIST_VIDEOS + 1,
    }
    with factory(options) as downloader:
        info = downloader.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise ValueError("YouTube returned no playlist information")

    if info.get("_type") not in {"playlist", "multi_video"}:
        entries = [info]
    else:
        entries = list(islice(info.get("entries") or (), MAX_YOUTUBE_PLAYLIST_VIDEOS + 1))

    truncated = len(entries) > MAX_YOUTUBE_PLAYLIST_VIDEOS
    videos = []
    for entry in entries[:MAX_YOUTUBE_PLAYLIST_VIDEOS]:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        video_id = quote(str(entry["id"]), safe="")
        videos.append({
            "url": "https://www.youtube.com/watch?v=" + video_id,
            "title": entry.get("title"),
        })

    return videos, truncated
