"""Unit tests for the local YouTube audio transcription fallback."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest

from app.adapters.youtube_audio import VideoDurationError, YouTubeAudioTranscriber


VIDEO_URL = "https://www.youtube.com/watch?v=abc123"


class FakeDownloaderFactory:
    """Build fake yt-dlp contexts and retain their observable activity."""

    def __init__(self, metadata):
        """Store the metadata returned for inspection and download.

        Args:
            metadata: Video information returned by the fake downloader.

        Returns:
            None.
        """
        self.metadata = metadata
        self.download_flags = []
        self.downloaded_paths = []

    def __call__(self, options):
        """Return one downloader configured with the caller's options.

        Args:
            options: yt-dlp option dictionary.

        Returns:
            A context-manager-compatible fake downloader.
        """
        return FakeDownloader(self, options)


class FakeDownloader:
    """Minimal yt-dlp surface used by the production adapter."""

    def __init__(self, owner, options):
        self.owner = owner
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download):
        """Record inspection or create the requested fake audio file."""
        del url
        self.owner.download_flags.append(download)
        info = dict(self.owner.metadata)
        if download:
            path = Path(self.prepare_filename(info))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio")
            self.owner.downloaded_paths.append(path)
        return info

    def prepare_filename(self, info):
        """Resolve the two yt-dlp placeholders used by the adapter."""
        return (
            self.options["outtmpl"]
            .replace("%(id)s", info["id"])
            .replace("%(ext)s", info.get("ext", "webm"))
        )


class FakeModel:
    """Return controlled Whisper output while measuring concurrency."""

    def __init__(self, result=None, failure=None, delay=0):
        self.result = result or {
            "text": " hello world ",
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 1.25, "text": " hello "},
                {"start": 1.25, "end": 2.5, "text": " world "},
            ],
        }
        self.failure = failure
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def transcribe(self, audio_path, **options):
        """Record the call, optionally fail, and expose peak concurrency."""
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.calls.append((audio_path, options))
            time.sleep(self.delay)
            if self.failure:
                raise self.failure
            return self.result
        finally:
            with self.lock:
                self.active -= 1


def metadata(**overrides):
    """Return ordinary single-video metadata with optional replacements."""
    result = {
        "id": "abc123",
        "title": "Example video",
        "duration": 2.5,
        "is_live": False,
        "ext": "webm",
        "webpage_url": VIDEO_URL,
    }
    result.update(overrides)
    return result


def build_transcriber(tmp_path, downloader, model):
    """Build a transcriber whose external dependencies are fully controlled."""
    loader_calls = []

    def load_model(name, download_root):
        loader_calls.append((name, download_root))
        return model

    transcriber = YouTubeAudioTranscriber(
        model_name="base",
        max_duration_seconds=1800,
        cache_dir=str(tmp_path / "models"),
        youtube_dl_factory=downloader,
        model_loader=load_model,
    )
    return transcriber, loader_calls


@pytest.mark.parametrize(
    ("video_metadata", "error_type", "message"),
    [
        (metadata(duration=1801), VideoDurationError, "30 minutes"),
        (metadata(duration=None), VideoDurationError, "duration"),
        (metadata(is_live=True), VideoDurationError, "Live"),
        (metadata(_type="playlist"), ValueError, "playlist"),
    ],
)
def test_invalid_video_is_rejected_before_download(
    tmp_path, video_metadata, error_type, message
):
    """Unbounded media must never reach download or model inference."""
    downloader = FakeDownloaderFactory(video_metadata)
    model = FakeModel()
    transcriber, loader_calls = build_transcriber(tmp_path, downloader, model)

    with pytest.raises(error_type, match=message):
        transcriber.transcribe(VIDEO_URL)

    assert downloader.download_flags == [False]
    assert loader_calls == []
    assert model.calls == []


def test_transcribe_normalizes_segments_and_removes_audio(tmp_path):
    """Whisper output must match the existing timestamped transcript contract."""
    downloader = FakeDownloaderFactory(metadata())
    model = FakeModel()
    transcriber, loader_calls = build_transcriber(tmp_path, downloader, model)

    result = transcriber.transcribe(VIDEO_URL)

    assert result["video_id"] == "abc123"
    assert result["text"] == "hello world"
    assert result["language"] == "en"
    assert result["duration"] == 2.5
    assert result["transcription_source"] == "whisper"
    assert result["segments"] == [
        {"start": 0.0, "end": 1.25, "duration": 1.25, "text": "hello"},
        {"start": 1.25, "end": 2.5, "duration": 1.25, "text": "world"},
    ]
    assert result["metadata"]["model"] == "base"
    assert result["metadata"]["transcription_source"] == "whisper"
    assert loader_calls == [("base", str(tmp_path / "models"))]
    assert model.calls[0][1] == {"fp16": False, "verbose": False}
    assert downloader.download_flags == [False, True]
    assert downloader.downloaded_paths
    assert all(not path.exists() for path in downloader.downloaded_paths)


def test_transcribe_removes_audio_when_whisper_fails(tmp_path):
    """A model failure must not leave downloaded media on disk."""
    downloader = FakeDownloaderFactory(metadata())
    model = FakeModel(failure=RuntimeError("decode failed"))
    transcriber, _ = build_transcriber(tmp_path, downloader, model)

    with pytest.raises(RuntimeError, match="decode failed"):
        transcriber.transcribe(VIDEO_URL)

    assert downloader.downloaded_paths
    assert all(not path.exists() for path in downloader.downloaded_paths)


def test_transcriptions_are_serialized_and_reuse_one_model(tmp_path):
    """Concurrent imports must not run two CPU-heavy Whisper jobs together."""
    downloader = FakeDownloaderFactory(metadata())
    model = FakeModel(delay=0.05)
    transcriber, loader_calls = build_transcriber(tmp_path, downloader, model)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(transcriber.transcribe, [VIDEO_URL, VIDEO_URL]))

    assert [result["text"] for result in results] == ["hello world", "hello world"]
    assert model.max_active == 1
    assert loader_calls == [("base", str(tmp_path / "models"))]
