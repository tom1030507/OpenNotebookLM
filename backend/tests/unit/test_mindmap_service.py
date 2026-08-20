"""Unit tests for the mind map service.

The tree has to be worth looking at whether or not an LLM is configured, so the
two halves are pinned separately: the structural topics that are always
available, and the LLM enrichment layered on top of them.
"""
from __future__ import annotations

import pytest

from app.services.mindmap import (
    MAX_TOPICS_PER_DOCUMENT,
    MindMapService,
    parse_llm_topics,
    topics_from_headings,
    topics_from_keywords,
)


class TestTopicsFromHeadings:
    """Headings are real document structure, so they are the first choice."""

    def test_uses_the_deepest_heading_segment(self):
        """A heading path names ancestors too; only the leaf is the topic."""
        assert topics_from_headings(["Guide/Setup/Install"]) == ["Install"]

    def test_keeps_first_occurrence_order_and_drops_repeats(self):
        """Every chunk of one section repeats its heading path."""
        paths = ["A/One", "A/One", "A/Two", "A/One"]

        assert topics_from_headings(paths) == ["One", "Two"]

    def test_ignores_missing_and_blank_paths(self):
        """PDF and video chunks have no heading path at all."""
        assert topics_from_headings([None, "", "  ", "A/Real"]) == ["Real"]

    def test_caps_the_number_of_topics(self):
        """An unbounded branch would be unreadable and unbounded in cost."""
        paths = ["Doc/H%d" % index for index in range(MAX_TOPICS_PER_DOCUMENT + 5)]

        assert len(topics_from_headings(paths)) == MAX_TOPICS_PER_DOCUMENT


class TestTopicsFromKeywords:
    """Without headings, salient words are the honest last resort."""

    def test_picks_the_most_frequent_meaningful_words(self):
        """Frequency across the document is the only signal available here."""
        text = "Rainfall shapes rainfall patterns. Monsoon rainfall and monsoon winds."

        assert topics_from_keywords(text, limit=2) == ["rainfall", "monsoon"]

    def test_skips_stopwords_and_short_tokens(self):
        """"the" occurs more often than any real term in ordinary prose."""
        text = "The the the of of a an it is to be climate climate"

        assert topics_from_keywords(text, limit=3) == ["climate"]

    def test_returns_nothing_for_empty_text(self):
        """A queued document has no content yet."""
        assert topics_from_keywords("") == []
        assert topics_from_keywords(None) == []


class TestParseLlmTopics:
    """The model's reply is untrusted input, so parsing has to be defensive."""

    def test_reads_topics_keyed_by_document_index(self):
        """Indexes, not ids, so the model never has to echo a uuid back."""
        reply = '{"documents": [{"index": 1, "topics": ["Alpha", "Beta"]}]}'

        assert parse_llm_topics(reply, document_count=1) == {1: ["Alpha", "Beta"]}

    def test_finds_the_object_inside_surrounding_prose(self):
        """Models prepend explanations and wrap replies in code fences."""
        reply = 'Sure!\n```json\n{"documents": [{"index": 2, "topics": ["Gamma"]}]}\n```'

        assert parse_llm_topics(reply, document_count=2) == {2: ["Gamma"]}

    def test_drops_indexes_outside_the_range_asked_about(self):
        """A hallucinated index would otherwise attach topics to nothing."""
        reply = '{"documents": [{"index": 9, "topics": ["Nowhere"]}]}'

        assert parse_llm_topics(reply, document_count=2) == {}

    def test_returns_nothing_for_unparseable_text(self):
        """The extractive fallback answer is prose, not JSON."""
        assert parse_llm_topics("I need an LLM configured to answer.", 1) == {}

    def test_caps_and_cleans_the_topics_it_accepts(self):
        """Blank and non-string entries would render as empty nodes."""
        topics = ["  Kept  ", "", None, 7] + ["T%d" % i for i in range(MAX_TOPICS_PER_DOCUMENT)]
        reply = '{"documents": [{"index": 1, "topics": %s}]}' % _json(topics)

        parsed = parse_llm_topics(reply, document_count=1)

        assert parsed[1][0] == "Kept"
        assert len(parsed[1]) == MAX_TOPICS_PER_DOCUMENT


def _json(value):
    """Serialize a fixture value the way a model would emit it."""
    import json

    return json.dumps(value)


class StubLLM:
    """LLM stand-in that returns a scripted reply and records its prompt."""

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


class FakeChunk:
    """Minimal stand-in for a Chunk row."""

    def __init__(self, text: str = "", heading_path=None):
        """Store the two fields the mind map reads."""
        self.text = text
        self.heading_path = heading_path


class FakeDocument:
    """Minimal stand-in for a Document row."""

    def __init__(self, doc_id: str, title: str, source_type: str = "pdf", chunks=None,
                 content: str = ""):
        """Store the fields the mind map reads."""
        self.id = doc_id
        self.title = title
        self.source_type = source_type
        self.content = content
        self.chunks = chunks or []


class TestBuildTree:
    """The shape the API hands to the browser."""

    @pytest.fixture
    def service(self):
        """A service whose LLM never answers, so structure is what is left."""
        return MindMapService(llm_service=StubLLM("not json", model="fallback"))

    def test_an_empty_project_is_a_lone_root(self, service):
        """A new project has no sources to branch into."""
        tree = service.build_tree("Notebook", [])

        assert tree["label"] == "Notebook"
        assert tree["kind"] == "project"
        assert tree["children"] == []

    def test_each_document_becomes_a_branch(self, service):
        """One branch per source is what makes the map navigable."""
        documents = [
            FakeDocument("d1", "First source", "url"),
            FakeDocument("d2", "Second source", "pdf"),
        ]

        tree = service.build_tree("Notebook", documents)

        assert [child["label"] for child in tree["children"]] == [
            "First source",
            "Second source",
        ]
        assert [child["document_id"] for child in tree["children"]] == ["d1", "d2"]
        assert {child["kind"] for child in tree["children"]} == {"document"}

    def test_node_ids_are_unique(self, service):
        """Two documents sharing a title must not share a node id."""
        documents = [
            FakeDocument("d1", "Same", chunks=[FakeChunk(heading_path="A/One")]),
            FakeDocument("d2", "Same", chunks=[FakeChunk(heading_path="A/One")]),
        ]

        ids = _all_ids(service.build_tree("Notebook", documents))

        assert len(ids) == len(set(ids))

    def test_headings_become_topic_nodes(self, service):
        """Heading structure is the mind map's natural second level."""
        document = FakeDocument(
            "d1",
            "Guide",
            "url",
            chunks=[FakeChunk(heading_path="Guide/Setup"), FakeChunk(heading_path="Guide/Usage")],
        )

        tree = service.build_tree("Notebook", [document])

        topics = tree["children"][0]["children"]
        assert [topic["label"] for topic in topics] == ["Setup", "Usage"]
        assert {topic["kind"] for topic in topics} == {"topic"}

    def test_keywords_stand_in_when_a_document_has_no_headings(self, service):
        """A plain PDF would otherwise be a branch with nothing on it."""
        document = FakeDocument(
            "d1",
            "Report",
            "pdf",
            chunks=[FakeChunk(text="Glacier melt accelerates. Glacier mass declines.")],
        )

        tree = service.build_tree("Notebook", [document])

        assert "glacier" in [
            topic["label"] for topic in tree["children"][0]["children"]
        ]


class TestGeneratedTopics:
    """What the LLM adds, and what happens when it cannot be used."""

    def test_llm_topics_replace_the_structural_ones(self):
        """The model sees the whole document; headings only see its skeleton."""
        service = MindMapService(
            llm_service=StubLLM('{"documents": [{"index": 1, "topics": ["Framing"]}]}'),
        )
        document = FakeDocument(
            "d1", "Guide", "url", chunks=[FakeChunk(heading_path="Guide/Setup")],
        )

        tree = service.build_tree("Notebook", [document])

        assert [t["label"] for t in tree["children"][0]["children"]] == ["Framing"]

    def test_the_model_is_reported_when_it_produced_the_topics(self):
        """Callers must be able to tell a generated map from an extracted one."""
        service = MindMapService(
            llm_service=StubLLM('{"documents": [{"index": 1, "topics": ["Framing"]}]}'),
        )

        service.build_tree("Notebook", [FakeDocument("d1", "Guide")])

        assert service.last_model == "stub-model"

    def test_the_fallback_is_reported_when_the_reply_is_unusable(self):
        """An unparseable reply means the structure did the work, not the model."""
        service = MindMapService(llm_service=StubLLM("sorry, no", model="stub-model"))

        service.build_tree("Notebook", [FakeDocument("d1", "Guide")])

        assert service.last_model == "fallback"

    def test_the_call_asks_for_as_much_as_the_model_will_give(self):
        """A reply cut off mid-JSON parses to nothing, so a smaller budget buys
        nothing. The provider clamps it to what one request may actually use."""
        stub = StubLLM('{"documents": []}')
        service = MindMapService(llm_service=stub)

        service.build_tree("Notebook", [FakeDocument("d1", "One")])

        assert stub.calls[0]["max_tokens"] is None

    def test_no_llm_call_is_made_for_an_empty_project(self):
        """There is nothing to ask about, and the call is not free."""
        stub = StubLLM('{"documents": []}')
        service = MindMapService(llm_service=stub)

        service.build_tree("Notebook", [])

        assert stub.prompts == []


def _all_ids(node) -> list:
    """Collect every node id in the tree, depth first."""
    ids = [node["id"]]
    for child in node.get("children", []):
        ids.extend(_all_ids(child))
    return ids
