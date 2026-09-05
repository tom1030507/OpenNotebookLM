"""Answers cite only the distinct passages actually sent to the model."""
import importlib
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def rag_module():
    """Load the real service even after route tests installed an import stub.

    Args:
        None.

    Returns:
        The production RAG module.
    """
    if not getattr(sys.modules.get("app.services.rag"), "__file__", None):
        sys.modules.pop("app.services.rag", None)
    return importlib.import_module("app.services.rag")


@pytest.fixture
def passages():
    """Return independent passages, including two on the same PDF page.

    Args:
        None.

    Returns:
        Three retrieval payloads.
    """
    return [
        {
            "chunk_id": f"chunk-{number}",
            "document_id": "paper",
            "document_title": "Paper",
            "text": text,
            "score": 0.8,
            "metadata": {"page_num": page},
        }
        for number, page, text in [
            (1, 1, "The proposed architecture uses attention."),
            (2, 7, "The French experiment uses a 32000 word-piece vocabulary."),
            (3, 1, "The model allows more parallel computation during training."),
        ]
    ]


def answer_with(rag_module, monkeypatch, passages, text):
    """Run real context and citation processing around a controlled generation.

    Args:
        rag_module: Production module.
        monkeypatch: Pytest replacement helper.
        passages: Retrieval output at the external search boundary.
        text: Provider response to process.

    Returns:
        The RAG response and captured provider request.
    """
    request = {}

    def generate(**kwargs):
        request.update(kwargs)
        return {"text": text, "model": "test-provider", "usage": {}}

    service = rag_module.RAGService(
        embedding_service=object(),
        llm_service=SimpleNamespace(generate=generate),
    )
    monkeypatch.setattr(service, "_retrieve_chunks", lambda **kwargs: passages)
    response = service.query(
        db=None, query="How does attention work?", use_cache=False,
    )
    return response, request


def test_only_cited_passages_are_returned_without_renumbering(
    rag_module, monkeypatch, passages,
):
    response, _ = answer_with(
        rag_module, monkeypatch, passages,
        "Parallel computation [Source 3] uses attention [Source 1].",
    )
    assert [source["id"] for source in response["sources"]] == [1, 3]
    assert [source["chunk_id"] for source in response["sources"]] == [
        "chunk-1", "chunk-3",
    ]
    assert response["chunks_used"] == 3


def test_an_uncited_answer_does_not_claim_to_have_used_every_passage(
    rag_module, monkeypatch, passages,
):
    response, _ = answer_with(
        rag_module, monkeypatch, passages, "The context does not answer this.",
    )
    assert response["sources"] == []


def test_repeated_retrieval_chunks_do_not_receive_multiple_source_numbers(
    rag_module, monkeypatch, passages,
):
    response, request = answer_with(
        rag_module, monkeypatch, [passages[0], passages[0], passages[2]],
        "Attention [Source 1] supports parallel training [Source 2].",
    )
    assert request["prompt"].count(passages[0]["text"]) == 1
    assert [source["chunk_id"] for source in response["sources"]] == [
        "chunk-1", "chunk-3",
    ]
    assert response["chunks_used"] == 2


def test_a_passage_dropped_by_the_context_budget_cannot_be_cited(
    rag_module, monkeypatch, passages,
):
    monkeypatch.setattr(rag_module.settings, "context_char_budget", 100)
    response, request = answer_with(
        rag_module, monkeypatch, passages,
        "Attention [Source 1]. Unsupported extra label [Source 2].",
    )
    assert passages[1]["text"] not in request["prompt"]
    assert [source["id"] for source in response["sources"]] == [1]
    assert "[Source 2]" not in response["answer"]
    assert response["chunks_used"] == 1


def test_a_nonexistent_source_label_is_not_published(
    rag_module, monkeypatch, passages,
):
    response, _ = answer_with(
        rag_module, monkeypatch, passages,
        "Attention [Source 1] with an invalid reference [Source 999].",
    )
    assert [source["id"] for source in response["sources"]] == [1]
    assert "[Source 999]" not in response["answer"]


@pytest.mark.parametrize("label", [
    "[Source\u202f1, Source\u202f3, Source\u202f999]",
    "[Source 1, 3, 999]",
])
def test_grouped_provider_citations_keep_each_valid_source(
    rag_module, monkeypatch, passages, label,
):
    response, _ = answer_with(
        rag_module, monkeypatch, passages, f"Attention enables parallel training {label}.",
    )
    assert response["answer"] == "Attention enables parallel training [Source 1][Source 3]."
    assert [source["id"] for source in response["sources"]] == [1, 3]


def test_extractive_fallback_preserves_its_passage_reference(
    rag_module, monkeypatch, passages,
):
    from app.services.llm import LLMService

    service = rag_module.RAGService(embedding_service=object(), llm_service=object())
    fallback = LLMService.__new__(LLMService)._fallback_response(
        service._build_prompt("What does the paper propose?", service._prepare_context(passages), True)
    )
    response, _ = answer_with(rag_module, monkeypatch, passages, fallback["text"])
    assert response["sources"]
    assert response["sources"][0]["chunk_id"] == "chunk-1"
    assert "[Source 1]" in response["answer"]
