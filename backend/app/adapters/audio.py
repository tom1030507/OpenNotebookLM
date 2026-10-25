"""Bounded local transcription for uploaded audio and YouTube audio."""
import json
import math
from pathlib import Path
import subprocess
import threading
from typing import Any, Callable, Dict, Optional

import structlog

logger = structlog.get_logger()

_MODEL_LOCK = threading.Lock()
_TRANSCRIPTION_LOCK = threading.Lock()
_MODELS: Dict[tuple[str, str], Any] = {}


class InvalidAudioFileError(ValueError):
    """Raised when an upload is not bounded, decodable audio."""


def _default_model_loader(model_name: str, download_root: str) -> Any:
    """Load one Whisper model without importing it at application startup.

    Args:
        model_name: Whisper model size or name.
        download_root: Persistent model cache directory.

    Returns:
        A loaded Whisper model.
    """
    import whisper

    return whisper.load_model(model_name, download_root=download_root)


class WhisperTranscriber:
    """Lazily cache Whisper and normalize its timestamped segment output."""

    def __init__(
        self,
        model_name: str,
        cache_dir: str,
        model_loader: Optional[Callable[[str, str], Any]] = None,
    ):
        """Configure a shared, lazy Whisper model.

        Args:
            model_name: Whisper model size or name.
            cache_dir: Persistent directory for downloaded model files.
            model_loader: Optional model loader for tests or alternatives.

        Returns:
            None.
        """
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.model_loader = model_loader or _default_model_loader

    def transcribe(self, file_path: str, duration: float) -> Dict[str, Any]:
        """Transcribe one audio file and return normalized text and segments.

        Args:
            file_path: Local path to an audio file.
            duration: Duration already verified by ffprobe.

        Returns:
            Normalized Whisper text, segments, and metadata.
        """
        # Whisper is CPU-heavy even on hosts with a GPU; serializing calls keeps
        # concurrent imports from multiplying model memory and core usage.
        with _TRANSCRIPTION_LOCK:
            model = self._get_model()
            result = model.transcribe(
                file_path,
                fp16=False,
                verbose=False,
            )
        return self._normalize_result(result, duration)

    def _get_model(self) -> Any:
        """Return the process-cached model, loading it once across callers."""
        key = (self.model_name, self.cache_dir)
        with _MODEL_LOCK:
            model = _MODELS.get(key)
            if model is None:
                Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
                model = self.model_loader(self.model_name, self.cache_dir)
                _MODELS[key] = model
            return model

    def _normalize_result(
        self,
        result: Dict[str, Any],
        duration: float,
    ) -> Dict[str, Any]:
        """Normalize Whisper's response for upload and YouTube sources.

        Args:
            result: Raw Whisper response.
            duration: Verified audio duration in seconds.

        Returns:
            Normalized text, timestamped segments, and transcription metadata.
        """
        segments = []
        for raw_segment in result.get("segments", []) or []:
            text = str(raw_segment.get("text", "")).strip()
            if not text:
                continue
            start = float(raw_segment.get("start", 0))
            end = float(raw_segment.get("end", start))
            segments.append({
                "start": start,
                "end": end,
                "duration": max(0.0, end - start),
                "text": text,
            })

        text = str(result.get("text", "")).strip()
        if not text:
            text = " ".join(segment["text"] for segment in segments)
        if not text:
            raise ValueError("No speech could be transcribed from this audio")

        language = str(result.get("language") or "unknown")
        metadata = {
            "duration": duration,
            "language": language,
            "model": self.model_name,
            "transcription_source": "whisper",
        }
        return {
            "text": text,
            "segments": segments,
            "duration": duration,
            "language": language,
            "metadata": metadata,
            "transcription_source": "whisper",
        }


class AudioAdapter:
    """Validate uploaded audio and produce a timestamped transcript."""

    def __init__(
        self,
        model_name: str,
        max_duration_seconds: int,
        cache_dir: str,
        model_loader: Optional[Callable[[str, str], Any]] = None,
    ):
        """Configure upload validation and local transcription.

        Args:
            model_name: Whisper model size or name.
            max_duration_seconds: Longest uploaded recording to transcribe.
            cache_dir: Persistent directory for downloaded Whisper model files.
            model_loader: Optional model loader for tests or alternatives.

        Returns:
            None.
        """
        self.max_duration_seconds = max_duration_seconds
        self.transcriber = WhisperTranscriber(
            model_name=model_name,
            cache_dir=cache_dir,
            model_loader=model_loader,
        )

    def validate_file(self, file_path: str) -> float:
        """Probe and reject non-audio or over-limit uploads before enqueue.

        Args:
            file_path: Local path to the uploaded file.

        Returns:
            The verified duration in seconds.

        Raises:
            InvalidAudioFileError: If the file is not audio or its duration
                cannot be bounded below the configured limit.
        """
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=codec_type,duration",
                    "-of",
                    "json",
                    file_path,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            result = json.loads(probe.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            raise InvalidAudioFileError(
                "The uploaded file is not valid audio"
            ) from error

        if not isinstance(result, dict):
            raise InvalidAudioFileError("The uploaded file is not valid audio")

        streams = result.get("streams") or []
        audio_streams = [
            stream for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ]
        if not audio_streams:
            raise InvalidAudioFileError(
                "The uploaded file does not contain an audio stream"
            )

        durations = []
        format_info = result.get("format") or {}
        if not isinstance(format_info, dict):
            format_info = {}
        duration_values = [format_info.get("duration")]
        duration_values.extend(stream.get("duration") for stream in audio_streams)
        for value in duration_values:
            try:
                duration = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(duration) and duration > 0:
                durations.append(duration)

        if not durations:
            raise InvalidAudioFileError(
                "The uploaded audio duration could not be determined"
            )

        duration = max(durations)
        if duration > self.max_duration_seconds:
            minutes = self.max_duration_seconds // 60
            limit = (
                f"{minutes} minutes"
                if self.max_duration_seconds % 60 == 0
                else f"{self.max_duration_seconds} seconds"
            )
            raise InvalidAudioFileError(
                f"Audio is longer than the {limit} limit"
            )
        return duration

    def transcribe_file(self, file_path: str) -> Dict[str, Any]:
        """Transcribe a validated upload and add two-minute Markdown headings.

        Args:
            file_path: Local path to the uploaded audio file.

        Returns:
            Transcript text, normalized timestamped segments, and metadata.
        """
        duration = self.validate_file(file_path)
        result = self.transcriber.transcribe(file_path, duration)
        lines = []
        current_bucket = None
        for segment in result["segments"]:
            bucket = max(0, int(segment["start"] // 120))
            if bucket != current_bucket:
                lines.append(f"## {self._format_timestamp(bucket * 120)}")
                current_bucket = bucket
            lines.append(segment["text"])
        if not lines:
            lines = ["## 00:00:00", result["text"]]
        result["text"] = "\n".join(lines)
        return result

    @staticmethod
    def _format_timestamp(seconds: int) -> str:
        """Format a non-negative offset as an HH:MM:SS heading.

        Args:
            seconds: Offset from the start of the recording.

        Returns:
            A zero-padded timestamp.
        """
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
