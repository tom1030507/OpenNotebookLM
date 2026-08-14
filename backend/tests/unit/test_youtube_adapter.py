"""Unit tests for the YouTube transcript adapter.

These tests drive the *real* youtube-transcript-api that is installed, and stub
out only its HTTP transport. Mocking ``YouTubeTranscriptApi`` itself would hide
exactly the class of bug these tests guard against: calling an entry point that
the pinned library version does not expose.
"""
import importlib
from types import SimpleNamespace

import pytest

from app.adapters.youtube import YouTubeAdapter

youtube_transcript_api = pytest.importorskip("youtube_transcript_api")
_api = importlib.import_module("youtube_transcript_api._api")

# The 0.x releases (this project pins 0.6.1) scrape the watch page with a
# ``requests.Session`` created inside ``YouTubeTranscriptApi.list_transcripts``.
# The 1.x releases build the session in ``__init__`` and talk to a different
# endpoint, so the canned bodies below only make sense for the 0.x transport.
HAS_LEGACY_TRANSPORT = hasattr(_api, "requests") and hasattr(
    youtube_transcript_api.YouTubeTranscriptApi, "list_transcripts"
)

VIDEO_ID = "dQw4w9WgXcQ"
TRANSCRIPT_URL = "https://example.invalid/timedtext?lang=en"

CAPTIONS_JSON = (
    '{"playerCaptionsTracklistRenderer": {'
    '"captionTracks": [{'
    '"baseUrl": "' + TRANSCRIPT_URL + '", '
    '"name": {"simpleText": "English (auto-generated)"}, '
    '"languageCode": "en", '
    '"kind": "asr", '
    '"isTranslatable": true'
    '}], '
    '"translationLanguages": [{'
    '"languageName": {"simpleText": "English"}, "languageCode": "en"'
    '}]}}'
)

WATCH_HTML = (
    '<!DOCTYPE html><html><body><script>var ytInitialPlayerResponse = '
    '{"captions":' + CAPTIONS_JSON + ',"videoDetails":{"videoId":"'
    + VIDEO_ID + '"}};</script></body></html>'
)

TRANSCRIPT_XML = (
    '<?xml version="1.0" encoding="utf-8"?><transcript>'
    '<text start="0.0" dur="2.5">Never gonna give you up</text>'
    '<text start="2.5" dur="2.5">[Music] never gonna let you down</text>'
    '</transcript>'
)


class FakeResponse:
    """Minimal stand-in for a ``requests.Response``."""

    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        return None


class FakeSession:
    """Minimal stand-in for a ``requests.Session`` (transport only)."""

    def __init__(self, routes):
        self.routes = routes
        self.requested_urls = []
        self.cookies = {}
        self.proxies = {}
        self.headers = {}

    def get(self, url, **kwargs):
        self.requested_urls.append(url)
        for fragment, body in self.routes.items():
            if fragment in url:
                return FakeResponse(body)
        raise AssertionError("unexpected request to {url}".format(url=url))

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.mark.skipif(
    not HAS_LEGACY_TRANSPORT,
    reason="installed youtube-transcript-api does not use the 0.x HTTP transport",
)
class TestYouTubeAdapterAgainstInstalledLibrary:
    """Exercise the adapter through the installed library, faking the network."""

    @pytest.fixture
    def session(self, monkeypatch):
        """Replace only the library's HTTP transport with canned responses."""
        fake_session = FakeSession({
            "/watch": WATCH_HTML,
            "timedtext": TRANSCRIPT_XML,
        })
        monkeypatch.setattr(
            _api,
            "requests",
            SimpleNamespace(Session=lambda: fake_session),
        )
        return fake_session

    def test_extract_transcript_returns_text_and_segments(self, session):
        """The adapter must use an entry point the installed library exposes."""
        adapter = YouTubeAdapter()

        result = adapter.extract_transcript(
            "https://www.youtube.com/watch?v={video_id}".format(video_id=VIDEO_ID)
        )

        assert result["video_id"] == VIDEO_ID
        assert result["language"] == "en"
        # Sound-effect annotations are stripped by _clean_transcript_text.
        assert result["text"] == (
            "Never gonna give you up never gonna let you down"
        )
        assert len(result["segments"]) == 2
        assert result["segments"][0] == {
            "start": 0.0,
            "end": 2.5,
            "duration": 2.5,
            "text": "Never gonna give you up",
        }
        assert result["duration"] == 5.0
        assert result["metadata"]["is_generated"] is True

    def test_extract_transcript_requests_video_id_not_url(self, session):
        """The watch page must be fetched by video ID, not by the full URL."""
        adapter = YouTubeAdapter()

        adapter.extract_transcript("https://youtu.be/{id}".format(id=VIDEO_ID))

        assert session.requested_urls[0].endswith(VIDEO_ID)
        assert TRANSCRIPT_URL in session.requested_urls


class TestYouTubeAdapterLibrarySurface:
    """The adapter must fail loudly when the library surface is unknown."""

    def test_unknown_library_surface_raises_explicit_error(self, monkeypatch):
        import app.adapters.youtube as youtube_module

        monkeypatch.setattr(
            youtube_module, "YouTubeTranscriptApi", SimpleNamespace()
        )
        adapter = YouTubeAdapter()

        with pytest.raises(RuntimeError) as exc_info:
            adapter.extract_transcript(
                "https://www.youtube.com/watch?v={id}".format(id=VIDEO_ID)
            )

        message = str(exc_info.value)
        assert "youtube-transcript-api" in message
        assert "list_transcripts" in message
        assert "list" in message
