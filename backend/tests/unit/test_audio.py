"""Tests for bounded local audio transcription."""
import importlib
import importlib.util
import json
from types import SimpleNamespace

import pytest


def audio_module():
    """Load the new adapter only after reporting its expected absence as RED."""
    spec = importlib.util.find_spec("app.adapters.audio")
    assert spec is not None, "local audio adapter is not implemented"
    return importlib.import_module("app.adapters.audio")


class FakeWhisperModel:
    """Record transcription arguments and return controlled Whisper output."""

    def __init__(self):
        self.calls = []

    def transcribe(self, file_path, **options):
        self.calls.append((file_path, options))
        return {
            "text": "first second third",
            "language": "en",
            "segments": [
                {"start": 1, "end": 4, "text": " first "},
                {"start": 119, "end": 121, "text": " second "},
                {"start": 240, "end": 241, "text": " third "},
            ],
        }


def install_probe(monkeypatch, duration=241, streams=None):
    """Return the configured ffprobe output for a controlled media file."""
    module = audio_module()
    response = {
        "format": {"duration": str(duration)},
        "streams": streams if streams is not None else [{"codec_type": "audio"}],
    }
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(response)),
    )
    return module


def test_audio_probe_accepts_the_duration_cap_and_rejects_longer_media(
    monkeypatch, tmp_path
):
    """The cap is inclusive and checked before Whisper starts."""
    module = install_probe(monkeypatch, duration=1800)
    adapter = module.AudioAdapter(
        model_name="base",
        max_duration_seconds=1800,
        cache_dir=str(tmp_path / "models"),
    )

    assert adapter.validate_file(str(tmp_path / "recording.mp3")) == 1800

    install_probe(monkeypatch, duration=1800.1)
    with pytest.raises(module.InvalidAudioFileError, match="30 minutes"):
        adapter.validate_file(str(tmp_path / "recording.mp3"))


def test_audio_probe_rejects_non_audio_content(monkeypatch, tmp_path):
    """A supported suffix cannot make a non-audio upload enter the queue."""
    module = install_probe(
        monkeypatch,
        streams=[{"codec_type": "video"}],
    )
    adapter = module.AudioAdapter(
        model_name="base",
        max_duration_seconds=1800,
        cache_dir=str(tmp_path / "models"),
    )

    with pytest.raises(module.InvalidAudioFileError, match="audio stream"):
        adapter.validate_file(str(tmp_path / "renamed.mp3"))


def test_audio_probe_rejects_unexpected_json_shape(monkeypatch, tmp_path):
    """Unexpected but valid JSON still becomes a client-facing audio error."""
    module = audio_module()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps([])),
    )
    adapter = module.AudioAdapter(
        model_name="base",
        max_duration_seconds=1800,
        cache_dir=str(tmp_path / "models"),
    )

    with pytest.raises(module.InvalidAudioFileError, match="valid audio"):
        adapter.validate_file(str(tmp_path / "recording.mp3"))


def test_transcription_formats_timestamp_sections_and_keeps_segments(
    monkeypatch, tmp_path
):
    """Audio transcripts carry two-minute headings and normalized offsets."""
    module = install_probe(monkeypatch)
    module._MODELS.clear()
    model = FakeWhisperModel()
    loader_calls = []
    adapter = module.AudioAdapter(
        model_name="base",
        max_duration_seconds=1800,
        cache_dir=str(tmp_path / "models"),
        model_loader=lambda name, cache: loader_calls.append((name, cache)) or model,
    )

    result = adapter.transcribe_file(str(tmp_path / "recording.mp3"))

    assert result["text"] == (
        "## 00:00:00\nfirst\nsecond\n## 00:04:00\nthird"
    )
    assert result["segments"] == [
        {"start": 1.0, "end": 4.0, "duration": 3.0, "text": "first"},
        {"start": 119.0, "end": 121.0, "duration": 2.0, "text": "second"},
        {"start": 240.0, "end": 241.0, "duration": 1.0, "text": "third"},
    ]
    assert result["duration"] == 241
    assert result["metadata"]["model"] == "base"
    assert loader_calls == [("base", str(tmp_path / "models"))]
    assert model.calls == [
        (str(tmp_path / "recording.mp3"), {"fp16": False, "verbose": False})
    ]


def test_uploaded_audio_and_youtube_share_one_whisper_model(
    monkeypatch, tmp_path
):
    """YouTube fallback and uploads resolve the same model cache entry."""
    from app.adapters.youtube_audio import YouTubeAudioTranscriber

    module = install_probe(monkeypatch, duration=2)
    module._MODELS.clear()
    model = FakeWhisperModel()
    loader_calls = []
    cache_dir = str(tmp_path / "models")
    audio = module.AudioAdapter(
        model_name="base",
        max_duration_seconds=1800,
        cache_dir=cache_dir,
        model_loader=lambda name, cache: loader_calls.append((name, cache)) or model,
    )

    class Downloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, download=False):
            return {
                "id": "video-1",
                "title": "Test video",
                "duration": 2,
                "webpage_url": "https://youtu.be/video-1",
            }

        def prepare_filename(self, _info):
            return str(tmp_path / "youtube.webm")

    youtube = YouTubeAudioTranscriber(
        model_name="base",
        max_duration_seconds=1800,
        cache_dir=cache_dir,
        youtube_dl_factory=Downloader,
        model_loader=lambda *_args: pytest.fail("Whisper model loaded twice"),
    )

    audio.transcribe_file(str(tmp_path / "recording.mp3"))
    youtube.transcribe("https://youtu.be/video-1")

    assert loader_calls == [("base", cache_dir)]
    assert len(model.calls) == 2
