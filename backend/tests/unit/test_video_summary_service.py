"""Unit tests for the video summary service.

The script has to be playable whether or not an LLM is configured, so the two
halves are pinned separately: the skeleton and the extracted content that are
always available, and the model's writing layered onto them.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.video_summary import (
    BULLET_MAX_CHARS,
    MAX_BULLETS_PER_SCENE,
    VideoSummaryService,
    estimate_seconds,
    leading_sentences,
    parse_llm_scenes,
)
from app.utils.time import utc_now


class TestLeadingSentences:
    """The middle of the fallback chain: sentences read aloud, keywords do not."""

    def test_takes_the_opening_sentences(self):
        """A document states its subject at the start."""
        text = "Hybrid retrieval beats one vector. Reranking then trims the list."

        assert leading_sentences(text, limit=2) == [
            "Hybrid retrieval beats one vector.",
            "Reranking then trims the list.",
        ]

    def test_ignores_fragments_that_are_not_sentences(self):
        """Extracted text is full of headers, page numbers and captions."""
        text = "Fig. 1. Page 4. Retrieval quality improves with hybrid search."

        assert leading_sentences(text, limit=3) == [
            "Retrieval quality improves with hybrid search.",
        ]

    def test_caps_the_number_of_bullets(self):
        """More than a handful of lines stops being a slide."""
        text = " ".join("Sentence number %d is here." % n for n in range(20))

        assert len(leading_sentences(text)) == MAX_BULLETS_PER_SCENE

    def test_shortens_a_long_sentence_at_a_word_boundary(self):
        """A slide line has to fit on the slide."""
        text = "%s ends here." % ("word " * 200)

        bullet = leading_sentences(text, limit=1)[0]

        assert len(bullet) <= BULLET_MAX_CHARS + 1
        assert bullet.endswith("…")
        assert "wor…" not in bullet

    def test_has_nothing_to_say_about_missing_text(self):
        """A document whose extraction failed carries no text at all."""
        assert leading_sentences(None) == []
        assert leading_sentences("   ") == []


class TestParseLlmScenes:
    """The reply is untrusted input: prose, fences and invented indexes."""

    def test_reads_the_agreed_shape(self):
        """Indexes rather than ids keep uuids out of the reply."""
        reply = json.dumps({"scenes": [{
            "index": 1,
            "headline": "Hybrid retrieval wins",
            "bullets": ["Two retrievers", "One reranker"],
            "narration": "This source argues for hybrid retrieval.",
        }]})

        parsed = parse_llm_scenes(reply, 1)

        assert parsed[1]["headline"] == "Hybrid retrieval wins"
        assert parsed[1]["bullets"] == ["Two retrievers", "One reranker"]
        assert parsed[1]["narration"] == "This source argues for hybrid retrieval."

    def test_ignores_fences_and_prose_around_the_json(self):
        """Models wrap JSON in explanation however firmly they are told not to."""
        reply = (
            "Sure! Here you go:\n```json\n"
            '{"scenes": [{"index": 1, "narration": "A sentence."}]}\n'
            "```\nHope that helps."
        )

        assert parse_llm_scenes(reply, 1)[1]["narration"] == "A sentence."

    def test_drops_entries_whose_index_is_not_a_document(self):
        """Models invent indexes, and an out-of-range one has no slide."""
        reply = json.dumps({"scenes": [
            {"index": 0, "narration": "Before the first."},
            {"index": 3, "narration": "After the last."},
            {"index": "1", "narration": "Not an integer."},
            {"index": 2, "narration": "Real."},
        ]})

        assert list(parse_llm_scenes(reply, 2)) == [2]

    def test_drops_an_entry_with_no_narration(self):
        """Narration is what makes it a video; bullets alone are a handout."""
        reply = json.dumps({"scenes": [
            {"index": 1, "headline": "Title only", "bullets": ["One"]},
        ]})

        assert parse_llm_scenes(reply, 1) == {}

    def test_caps_the_bullets_on_a_scene(self):
        """A model asked for four will sometimes send nine."""
        reply = json.dumps({"scenes": [{
            "index": 1,
            "narration": "A sentence.",
            "bullets": ["Point %d" % n for n in range(MAX_BULLETS_PER_SCENE + 5)],
        }]})

        assert len(parse_llm_scenes(reply, 1)[1]["bullets"]) == MAX_BULLETS_PER_SCENE

    def test_a_prose_reply_yields_nothing(self):
        """With no provider configured the service answers with prose."""
        assert parse_llm_scenes("Configure an LLM for better answers.", 2) == {}


class TestEstimateSeconds:
    """Only used to draw the progress bar; playback is driven by the voice."""

    def test_grows_with_the_amount_of_narration(self):
        """A longer script takes longer to read out."""
        short = estimate_seconds(["One two three."])
        long = estimate_seconds(["word " * 200])

        assert long > short

    def test_gives_a_silent_scene_a_moment_on_screen(self):
        """A scene with no narration still has to be readable."""
        assert estimate_seconds(["", ""]) >= 2


class StubLLM:
    """LLM stand-in that returns a scripted reply and records its calls."""

    def __init__(self, text: str, model: str = "stub-model"):
        """Store the reply this stub will give.

        Args:
            text: Reply body.
            model: Model name to report, as the real service does.
        """
        self.text = text
        self.model = model
        self.prompts: list[str] = []
        self.calls: list[dict] = []

    def generate(self, prompt: str, **kwargs) -> dict:
        """Return the scripted reply, recording the call for assertions."""
        self.prompts.append(prompt)
        self.calls.append(kwargs)
        return {
            "text": self.text,
            "model": self.model,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


class ExplodingLLM:
    """LLM stand-in for a provider that is configured but unreachable."""

    def generate(self, prompt: str, **kwargs) -> dict:
        """Fail the way a dead provider does."""
        raise ConnectionError("no route to model server")


class FakeChunk:
    """Minimal stand-in for a Chunk row."""

    def __init__(self, text: str = "", heading_path=None):
        """Store the two fields the script reads."""
        self.text = text
        self.heading_path = heading_path


class FakeDocument:
    """Minimal stand-in for a Document row."""

    def __init__(self, doc_id: str, title: str, source_type: str = "pdf",
                 chunks=None, content: str = ""):
        """Store the fields the script reads."""
        self.id = doc_id
        self.title = title
        self.source_type = source_type
        self.content = content
        self.chunks = chunks or []


def _scenes(service, documents, project_name="Notebook"):
    """Build a script and return just its scenes."""
    return service.build_scenes(project_name, documents, utc_now())[0]


class TestSkeleton:
    """Scene count and order are decided by code, not by the model."""

    @pytest.fixture
    def service(self):
        """A service whose LLM never answers usably."""
        return VideoSummaryService(llm_service=StubLLM("not json", model="stub-model"))

    def test_an_empty_project_is_a_title_and_a_closing(self, service):
        """Nothing to summarise, but the endpoint is not an error."""
        scenes = _scenes(service, [])

        assert [scene["kind"] for scene in scenes] == ["title", "closing"]

    def test_every_source_gets_one_scene_between_them(self, service):
        """The skeleton is what makes the length predictable."""
        documents = [FakeDocument("d%d" % n, "Source %d" % n) for n in range(3)]

        scenes = _scenes(service, documents)

        assert [scene["kind"] for scene in scenes] == [
            "title", "source", "source", "source", "closing",
        ]

    def test_scene_ids_are_unique(self, service):
        """Two sources sharing a title must not share a scene id."""
        documents = [FakeDocument("d1", "Same"), FakeDocument("d2", "Same")]

        ids = [scene["id"] for scene in _scenes(service, documents)]

        assert len(ids) == len(set(ids))

    def test_the_title_scene_names_the_project_and_counts_its_sources(self, service):
        """The opening card is the only place the whole project is stated."""
        scenes = _scenes(service, [FakeDocument("d1", "One")], project_name="RAG notes")

        title = scenes[0]
        assert title["headline"] == "RAG notes"
        assert "1 source" in " ".join(title["bullets"])
        assert "RAG notes" in title["narration"]

    def test_a_source_scene_carries_the_document_it_came_from(self, service):
        """Selecting a scene has to be able to name and open its source."""
        scenes = _scenes(service, [FakeDocument("d1", "Retrieval notes", "url")])

        source = scenes[1]
        assert source["document_id"] == "d1"
        assert source["source_label"] == "Retrieval notes"

    def test_the_closing_scene_recaps_the_source_headlines(self, service):
        """The recap is composed from the scenes, never asked of the model."""
        documents = [FakeDocument("d1", "First"), FakeDocument("d2", "Second")]

        scenes = _scenes(service, documents)

        assert scenes[-1]["bullets"] == ["First", "Second"]

    def test_the_closing_recap_stays_a_slide(self, service):
        """A project with fifty sources still gets a readable last card."""
        documents = [
            FakeDocument("d%d" % n, "Source %d" % n)
            for n in range(MAX_BULLETS_PER_SCENE + 6)
        ]

        assert len(_scenes(service, documents)[-1]["bullets"]) == MAX_BULLETS_PER_SCENE

    def test_every_scene_has_narration_to_read_out(self, service):
        """A silent scene is a gap in the video, not a scene."""
        documents = [FakeDocument("d1", "One", chunks=[FakeChunk(text="")])]

        assert all(scene["narration"].strip() for scene in _scenes(service, documents))


class TestFallbackChain:
    """What a source scene says when no model wrote it."""

    @pytest.fixture
    def service(self):
        """A service whose LLM never answers usably."""
        return VideoSummaryService(llm_service=StubLLM("not json", model="stub-model"))

    def test_headings_become_the_bullets(self, service):
        """Heading structure is real structure, already in the database."""
        document = FakeDocument("d1", "Guide", "url", chunks=[
            FakeChunk(heading_path="Guide/Setup"),
            FakeChunk(heading_path="Guide/Usage"),
        ])

        assert _scenes(service, [document])[1]["bullets"] == ["Setup", "Usage"]

    def test_opening_sentences_stand_in_without_headings(self, service):
        """The common case is a PDF with no headings at all."""
        document = FakeDocument("d1", "Report", "pdf", chunks=[
            FakeChunk(text="Glacier melt accelerates each decade. Mass balance falls."),
        ])

        bullets = _scenes(service, [document])[1]["bullets"]

        assert bullets[0] == "Glacier melt accelerates each decade."

    def test_keywords_are_the_last_resort(self, service):
        """Text with no sentence ends still has salient words."""
        document = FakeDocument("d1", "Notes", "pdf", chunks=[
            FakeChunk(text="glacier glacier glacier melt melt permafrost"),
        ])

        assert "glacier" in _scenes(service, [document])[1]["bullets"]

    def test_the_headline_falls_back_to_the_document_title(self, service):
        """Without a model there is nobody to write a headline."""
        assert _scenes(service, [FakeDocument("d1", "Retrieval notes")])[1][
            "headline"
        ] == "Retrieval notes"

    def test_the_narration_names_the_source_and_its_bullets(self, service):
        """Flat, but honest, and model_used says where it came from."""
        document = FakeDocument("d1", "Guide", "url", chunks=[
            FakeChunk(heading_path="Guide/Setup"),
        ])

        narration = _scenes(service, [document])[1]["narration"]

        assert "Guide" in narration
        assert "Setup" in narration


class TestGeneratedScenes:
    """What the LLM adds, and what happens when it cannot be used."""

    def _reply(self, **fields):
        """Serialise a one-scene reply for document 1."""
        return json.dumps({"scenes": [{"index": 1, **fields}]})

    def test_the_model_writes_the_source_scene(self):
        """The model sees the document; headings only see its skeleton."""
        service = VideoSummaryService(llm_service=StubLLM(self._reply(
            headline="Why hybrid retrieval wins",
            bullets=["Two retrievers", "One reranker"],
            narration="This source argues for hybrid retrieval.",
        )))
        document = FakeDocument("d1", "Guide", "url", chunks=[
            FakeChunk(heading_path="Guide/Setup"),
        ])

        scene = _scenes(service, [document])[1]

        assert scene["headline"] == "Why hybrid retrieval wins"
        assert scene["bullets"] == ["Two retrievers", "One reranker"]
        assert scene["narration"] == "This source argues for hybrid retrieval."

    def test_structural_bullets_fill_in_when_the_model_sends_none(self):
        """A scene with a paragraph and no points is not a slide."""
        service = VideoSummaryService(llm_service=StubLLM(self._reply(
            headline="Written", narration="A sentence.",
        )))
        document = FakeDocument("d1", "Guide", "url", chunks=[
            FakeChunk(heading_path="Guide/Setup"),
        ])

        assert _scenes(service, [document])[1]["bullets"] == ["Setup"]

    def test_the_model_is_reported_when_it_wrote_the_script(self):
        """A generated script and an extracted one look alike on screen."""
        service = VideoSummaryService(
            llm_service=StubLLM(self._reply(narration="A sentence.")),
        )

        _, model_used = service.build_scenes(
            "Notebook", [FakeDocument("d1", "Guide")], utc_now(),
        )

        assert model_used == "stub-model"

    def test_the_fallback_is_reported_when_the_reply_is_unusable(self):
        """Then the document's own structure did the work, not the model."""
        service = VideoSummaryService(llm_service=StubLLM("sorry, no"))

        _, model_used = service.build_scenes(
            "Notebook", [FakeDocument("d1", "Guide")], utc_now(),
        )

        assert model_used == "fallback"

    def test_a_dead_provider_does_not_fail_the_script(self):
        """The extracted script is still worth playing."""
        service = VideoSummaryService(llm_service=ExplodingLLM())

        scenes, model_used = service.build_scenes(
            "Notebook", [FakeDocument("d1", "Guide")], utc_now(),
        )

        assert len(scenes) == 3
        assert model_used == "fallback"

    def test_the_call_asks_for_as_much_as_the_model_will_give(self):
        """A script cut off mid-JSON parses to nothing, so there is no reason to
        ask for less. Sizing the request belongs to the provider, which is the
        only layer that knows what one request may actually use."""
        stub = StubLLM('{"scenes": []}')
        service = VideoSummaryService(llm_service=stub)

        service.build_scenes("Notebook", [FakeDocument("d1", "One")], utc_now())

        assert stub.calls[0]["max_tokens"] is None

    def test_no_llm_call_is_made_for_an_empty_project(self):
        """There is nothing to ask about, and the call is not free."""
        stub = StubLLM('{"scenes": []}')
        service = VideoSummaryService(llm_service=stub)

        service.build_scenes("Notebook", [], utc_now())

        assert stub.prompts == []

    def test_the_prompt_carries_every_source_once(self):
        """One call per script, not one per source: cost must not scale."""
        stub = StubLLM('{"scenes": []}')
        service = VideoSummaryService(llm_service=stub)
        documents = [FakeDocument("d1", "Alpha"), FakeDocument("d2", "Beta")]

        service.build_scenes("Notebook", documents, utc_now())

        assert len(stub.prompts) == 1
        assert "Alpha" in stub.prompts[0]
        assert "Beta" in stub.prompts[0]


# How long a thread in these tests waits for its counterpart before giving up.
# Generous, because it is only ever reached when the interleaving under test has
# broken; a passing run never waits this long.
HANDOFF_TIMEOUT_SECONDS = 5


class FakeProject:
    """Minimal stand-in for a Project row."""

    def __init__(self, name: str, project_id: str = None):
        """Store the two fields the script reads."""
        self.id = project_id or "project-%s" % name.lower()
        self.name = name


class PairedLLM:
    """LLM stand-in that answers two concurrent callers differently.

    Which reply a caller gets is keyed off the source title in its prompt, so a
    thread can assert on the model it was itself promised rather than on
    whichever reply happened to arrive. A reply can also be held back until the
    other thread reaches a known point, which is what turns a race into a fixed
    order the test can assert on.
    """

    def __init__(self, models_by_source: dict, hold_until: dict = None):
        """Script one reply per source, and any gate that reply waits on.

        Args:
            models_by_source: Source title -> model name to report for it. The
                title is matched against the prompt.
            hold_until: Source title -> event that must be set before that
                source's reply is returned.
        """
        self.models_by_source = dict(models_by_source)
        self.hold_until = dict(hold_until or {})

    def generate(self, prompt: str, **kwargs) -> dict:
        """Return the reply scripted for whichever source this prompt covers."""
        source = next(
            title for title in self.models_by_source if title in prompt
        )

        gate = self.hold_until.get(source)
        if gate is not None:
            assert gate.wait(timeout=HANDOFF_TIMEOUT_SECONDS), (
                "the other script never reached the handoff point"
            )

        return {
            "text": json.dumps({"scenes": [{
                "index": 1,
                "headline": source,
                "bullets": [source],
                "narration": "This source is %s." % source,
            }]}),
            "model": self.models_by_source[source],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


class PausingDocument:
    """A document that stops the script that reads it, once.

    The gap this aims at — between a script learning which model wrote it and
    that answer reaching the response — is microseconds wide, so two threads
    left to collide on their own would make the test lucky rather than correct.
    `build_scenes` reads a document's `id` only after the model has answered, so
    pausing there holds the gap open for exactly as long as the other thread
    needs.
    """

    def __init__(self, doc_id: str, title: str, on_first_read):
        """Store the fields the script reads, plus the pause to take.

        Args:
            doc_id: The document id, handed out by the property below.
            title: Document title. Also how `PairedLLM` recognises the prompt.
            on_first_read: Called the first time `id` is read, and only then —
                a scene reads it twice.
        """
        self._id = doc_id
        self.title = title
        self.source_type = "pdf"
        self.content = ""
        self.chunks = []
        self._on_first_read = on_first_read
        self._read = False

    @property
    def id(self) -> str:
        """The document id, pausing the script the first time it is asked for."""
        if not self._read:
            self._read = True
            self._on_first_read()

        return self._id


class TestConcurrentGeneration:
    """One service instance serves every request, from a threadpool.

    The route is a plain `def`, so FastAPI runs it in a worker thread and two
    projects can be summarised at the same time. Anything a script records on
    the service itself is therefore visible to the other script.
    """

    def test_each_script_reports_the_model_that_wrote_it(self, monkeypatch):
        """Two overlapping scripts must not swap model names.

        The first script is held partway through its scenes until the second
        has finished asking its own model, which pins the interleaving to the
        one order that matters: the second script's answer is the most recent
        thing written when the first assembles its response.
        """
        first_script_started_scenes = threading.Event()
        second_script_has_its_model = threading.Event()

        def hold_first_script():
            """Let the second script overtake, then carry on."""
            first_script_started_scenes.set()
            assert second_script_has_its_model.wait(
                timeout=HANDOFF_TIMEOUT_SECONDS
            ), "the second script never asked its model"

        documents = {
            "Alpha": [PausingDocument("d1", "Alpha", hold_first_script)],
            "Beta": [
                PausingDocument("d2", "Beta", second_script_has_its_model.set),
            ],
        }
        service = VideoSummaryService(
            llm_service=PairedLLM(
                {"Alpha": "model-alpha", "Beta": "model-beta"},
                # The second script may not answer until the first is past the
                # point where it recorded its own model.
                hold_until={"Beta": first_script_started_scenes},
            ),
        )
        monkeypatch.setattr(
            "app.services.video_summary.project_documents",
            lambda db, project: documents[project.name],
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            scripts = {
                name: pool.submit(service.generate, None, FakeProject(name))
                for name in ("Alpha", "Beta")
            }
            summaries = {
                name: script.result(timeout=HANDOFF_TIMEOUT_SECONDS * 2)
                for name, script in scripts.items()
            }

        assert summaries["Alpha"]["model_used"] == "model-alpha"
        assert summaries["Beta"]["model_used"] == "model-beta"
