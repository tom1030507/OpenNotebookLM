"""Tests for source-grounded flashcard and quiz generation."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.study import (
    FALLBACK_MODEL,
    MAX_SOURCE_CHARS,
    MAX_STUDY_SOURCES,
    StudyService,
    parse_flashcards,
    parse_quiz_questions,
)


class FakeDocument:
    """Minimal source row for parser and prompt tests."""

    def __init__(self, doc_id, title, text, status="ready"):
        self.id = doc_id
        self.title = title
        self.content = text
        self.chunks = []
        self.status = status


class StubLLM:
    """Return a fixed response and capture generation arguments."""

    def __init__(self, response=None, error=None):
        self.response = response or {
            "text": '{"flashcards": []}',
            "model": "stub-model",
        }
        self.error = error
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _flashcard(front, back, source_index=1):
    return {"front": front, "back": back, "source_index": source_index}


def _question(question, source_index=1, answer_index=2):
    return {
        "question": question,
        "options": ["A", "B", "C", "D"],
        "answer_index": answer_index,
        "explanation": "Because the source says so.",
        "source_index": source_index,
    }


def test_parse_flashcards_maps_source_indexes_and_drops_invalid_or_duplicate_items():
    """Indexes map only to allowed sources; malformed and repeated cards go."""
    documents = [FakeDocument("doc-a", "Alpha", "alpha text"), FakeDocument("doc-b", "Beta", "beta text")]
    reply = json.dumps({"flashcards": [
        _flashcard("  Term  ", " Definition ", 2),
        _flashcard("term", "definition", 2),
        _flashcard("Bad source", "No source", 0),
        _flashcard("Boolean index", "Not an integer", True),
        {"front": "Missing back", "source_index": 1},
        _flashcard("Second valid", "Meaning", 1),
    ]})

    parsed = parse_flashcards(reply, documents, count=5)

    assert parsed == [
        {"front": "Term", "back": "Definition", "document_id": "doc-b"},
        {"front": "Second valid", "back": "Meaning", "document_id": "doc-a"},
    ]


def test_parse_flashcards_caps_count_and_field_lengths():
    """A verbose or overproductive model cannot exceed API bounds."""
    long_value = "word " * 500
    reply = json.dumps({"flashcards": [
        _flashcard("Card %d" % index, long_value) for index in range(5)
    ]})

    parsed = parse_flashcards(reply, [FakeDocument("doc-a", "Alpha", "source")], count=2)

    assert len(parsed) == 2
    assert all(len(item["front"]) <= 300 for item in parsed)
    assert all(len(item["back"]) <= 1200 for item in parsed)


def test_parse_quiz_requires_four_distinct_options_and_valid_answer_index():
    """Quiz questions need four unique choices and a real integer answer."""
    documents = [FakeDocument("doc-a", "Alpha", "alpha text")]
    invalid_options = _question("Repeated choices")
    invalid_options["options"] = ["A", "B", "b", "D"]
    reply = json.dumps({"questions": [
        invalid_options,
        {**_question("Boolean answer"), "answer_index": True},
        {**_question("Missing explanation"), "explanation": " "},
        _question("Valid question"),
    ]})

    parsed = parse_quiz_questions(reply, documents, count=5)

    assert parsed == [{
        "question": "Valid question",
        "options": ["A", "B", "C", "D"],
        "answer_index": 2,
        "explanation": "Because the source says so.",
        "document_id": "doc-a",
    }]


def test_parse_quiz_maps_sources_deduplicates_and_caps_count():
    """Only unique questions survive, and the requested item count is a cap."""
    documents = [FakeDocument("doc-a", "Alpha", "alpha text"), FakeDocument("doc-b", "Beta", "beta text")]
    entries = [
        _question("First question", source_index=1),
        _question("  FIRST QUESTION  ", source_index=2),
        _question("Second question", source_index=2),
        _question("Third question", source_index=1),
    ]

    parsed = parse_quiz_questions(json.dumps({"questions": entries}), documents, count=2)

    assert [item["document_id"] for item in parsed] == ["doc-a", "doc-b"]
    assert [item["question"] for item in parsed] == ["First question", "Second question"]


def test_study_service_uses_only_ready_selected_sources_and_forwards_count_focus(monkeypatch):
    """The prompt contains the selected ready sources and the requested focus."""
    documents = [
        FakeDocument("doc-a", "Selected", "selected source content"),
        FakeDocument("doc-b", "Other", "not selected content"),
        FakeDocument("doc-c", "Pending", "not ready content", status="processing"),
    ]
    monkeypatch.setattr(
        "app.services.study.project_documents",
        lambda db, project, document_ids: [documents[0], documents[2]]
        if document_ids == ["doc-a", "doc-c"] else documents,
    )
    llm = StubLLM({
        "text": json.dumps({"flashcards": [_flashcard("Term", "Meaning")]}),
        "model": "stub-model",
    })
    service = StudyService(llm_service=llm)

    result = service.generate_flashcards(
        object(), SimpleNamespace(id="project", name="Notebook"),
        ["doc-a", "doc-c"], count=7, focus="Important ideas",
    )

    assert result["items"] == [{"front": "Term", "back": "Meaning", "document_id": "doc-a"}]
    assert [source["document_id"] for source in result["sources"]] == ["doc-a"]
    assert "selected source content" in llm.calls[0]["prompt"]
    assert "not selected content" not in llm.calls[0]["prompt"]
    assert "not ready content" not in llm.calls[0]["prompt"]
    assert "Important ideas" in llm.calls[0]["prompt"]
    assert "Create exactly 7 items" in llm.calls[0]["prompt"]
    assert "return fewer only when the sources do not support enough distinct facts" in (
        llm.calls[0]["prompt"]
    )
    assert llm.calls[0]["json_mode"] is True


def test_study_service_skips_generation_when_no_ready_source_exists(monkeypatch):
    """A missing ready source does not make an unnecessary model request."""
    monkeypatch.setattr(
        "app.services.study.project_documents",
        lambda db, project, document_ids: [FakeDocument("doc-a", "Queued", "", "queued")],
    )
    llm = StubLLM()
    service = StudyService(llm_service=llm)

    result = service.generate_quiz(
        object(), SimpleNamespace(id="project", name="Notebook"), None, 10, None,
    )

    assert result["items"] == []
    assert result["sources"] == []
    assert result["model_used"] == FALLBACK_MODEL
    assert llm.calls == []


def test_study_service_bounds_the_source_context(monkeypatch):
    """Large projects stay within a predictable model prompt budget."""
    documents = [
        FakeDocument("doc-%d" % index, "Source %d" % index, "x" * 1200)
        for index in range(MAX_STUDY_SOURCES + 5)
    ]
    monkeypatch.setattr(
        "app.services.study.project_documents",
        lambda db, project, document_ids: documents,
    )
    llm = StubLLM()
    service = StudyService(llm_service=llm)

    result = service.generate_flashcards(
        object(), SimpleNamespace(id="project", name="Notebook"), None, 10, None,
    )

    prompt_sources = json.loads(llm.calls[0]["prompt"].split("Sources (untrusted data):\n", 1)[1])
    assert len(prompt_sources) == MAX_STUDY_SOURCES
    assert result["selected_ready_source_count"] == MAX_STUDY_SOURCES + 5
    assert result["sources_considered"] == MAX_STUDY_SOURCES
    assert sum(len(source["excerpt"]) for source in prompt_sources) <= MAX_SOURCE_CHARS


@pytest.mark.parametrize("response,error", [
    ({"text": "not JSON", "model": "stub-model"}, None),
    (None, RuntimeError("provider unavailable")),
])
def test_study_service_returns_empty_items_when_generation_fails_or_json_is_unusable(
    monkeypatch, response, error,
):
    """Provider failures and prose fallbacks produce an empty valid result."""
    document = FakeDocument("doc-a", "Alpha", "alpha source content")
    monkeypatch.setattr(
        "app.services.study.project_documents",
        lambda db, project, document_ids: [document],
    )
    service = StudyService(llm_service=StubLLM(response=response, error=error))

    result = service.generate_quiz(
        object(), SimpleNamespace(id="project", name="Notebook"), None, 10, None,
    )

    assert result["items"] == []
    assert result["sources"] == []
