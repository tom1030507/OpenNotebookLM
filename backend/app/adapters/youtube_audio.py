"""Local audio transcription fallback for captionless YouTube videos."""
from pathlib import Path
import tempfile
from typing import Any, Callable, Dict, Optional

import structlog

from app.adapters.audio import WhisperTranscriber

logger = structlog.get_logger()


class VideoDurationError(ValueError):
    """Raised when a video's duration makes local transcription unsafe."""


def _default_youtube_dl_factory(options: Dict[str, Any]) -> Any:
    """Build the real yt-dlp client without importing it at app startup.

    Args:
        options: Options passed to ``yt_dlp.YoutubeDL``.

    Returns:
        A configured yt-dlp client.
    """
    import yt_dlp

    return yt_dlp.YoutubeDL(options)


class YouTubeAudioTranscriber:
    """Download bounded YouTube audio and transcribe it with local Whisper."""

    def __init__(
        self,
        model_name: str,
        max_duration_seconds: int,
        cache_dir: str,
        youtube_dl_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
        model_loader: Optional[Callable[[str, str], Any]] = None,
    ):
        """Configure bounded audio download and model loading.

        Args:
            model_name: Multilingual Whisper model to load.
            max_duration_seconds: Longest video accepted for local transcription.
            cache_dir: Persistent directory for downloaded Whisper model files.
            youtube_dl_factory: Optional yt-dlp factory for tests or alternatives.
            model_loader: Optional Whisper model loader for tests or alternatives.

        Returns:
            None.
        """
        self.model_name = model_name
        self.max_duration_seconds = max_duration_seconds
        self.cache_dir = cache_dir
        self.youtube_dl_factory = (
            youtube_dl_factory or _default_youtube_dl_factory
        )
        self.transcriber = WhisperTranscriber(
            model_name=model_name,
            cache_dir=cache_dir,
            model_loader=model_loader,
        )

    def transcribe(self, url: str) -> Dict[str, Any]:
        """Transcribe one bounded, non-live YouTube video's audio.

        Args:
            url: YouTube watch URL.

        Returns:
            The existing transcript result shape with timestamped segments.
        """
        with self.youtube_dl_factory(self._download_options()) as downloader:
            info = downloader.extract_info(url, download=False)

        self._validate_video(info)

        with tempfile.TemporaryDirectory(
            prefix="opennotebook-youtube-"
        ) as temp_dir:
            options = self._download_options(
                str(Path(temp_dir) / "%(id)s.%(ext)s")
            )
            with self.youtube_dl_factory(options) as downloader:
                downloaded_info = downloader.extract_info(url, download=True)
                audio_path = downloader.prepare_filename(downloaded_info)

            transcription = self.transcriber.transcribe(
                audio_path,
                float(info["duration"]),
            )
            normalized = self._normalize_result(url, info, transcription)

        logger.info(
            "YouTube audio transcribed locally",
            video_id=normalized["video_id"],
            duration=normalized["duration"],
            language=normalized["language"],
            model=self.model_name,
        )
        return normalized

    def _download_options(self, output_template: Optional[str] = None) -> Dict[str, Any]:
        """Return yt-dlp options for one quiet, audio-only video operation."""
        options: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
        }
        if output_template:
            options["outtmpl"] = output_template
        return options

    def _validate_video(self, info: Dict[str, Any]) -> None:
        """Reject media whose size cannot be bounded before download."""
        if info.get("_type") in {"playlist", "multi_video"}:
            raise ValueError("A playlist cannot be transcribed; add one video URL")

        if info.get("is_live"):
            raise VideoDurationError("Live videos cannot be transcribed")

        duration = info.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise VideoDurationError(
                "Video duration is unavailable; only recorded videos are supported"
            )

        if duration > self.max_duration_seconds:
            minutes = self.max_duration_seconds // 60
            raise VideoDurationError(
                f"Video is longer than the {minutes} minutes limit"
            )

    def _normalize_result(
        self,
        url: str,
        info: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add YouTube identity to the shared Whisper result contract.

        Args:
            url: Original YouTube watch URL.
            info: Metadata returned by yt-dlp.
            result: Normalized shared Whisper transcription.

        Returns:
            The existing YouTube transcript result shape.
        """
        video_id = str(info.get("id") or "unknown")
        metadata = {
            **result["metadata"],
            "video_id": video_id,
            "title": info.get("title", ""),
        }
        return {
            **result,
            "video_id": video_id,
            "url": info.get("webpage_url") or url,
            "metadata": metadata,
        }
