import numpy as np

from app.services.citation_support import check_citation_support


class StubEmbedder:
    def __init__(self):
        self.calls = []

    def generate_embedding(self, texts, role):
        self.calls.append((list(texts), role))
        if role == "query":
            return np.array([[1.0, 0.0], [1.0, 0.0]])
        return np.array([[1.0, 0.0], [0.0, 1.0]])


def test_scores_each_cjk_and_english_sentence_against_only_its_citations():
    embedder = StubEmbedder()
    chunks = [
        {"text": "English passage supports the first claim."},
        {"text": "中文段落支持另一個主張。"},
        {"text": "An uncited passage matches the second claim."},
    ]

    checks = check_citation_support(
        "First claim [Source 1]. 第二句 [Source 2]。No citation here.",
        chunks,
        embedder,
        threshold=0.5,
    )

    assert checks == [
        {"sentence_index": 0, "cited_labels": [1], "score": 1.0, "supported": True},
        {"sentence_index": 1, "cited_labels": [2], "score": 0.0, "supported": False},
    ]
    assert [role for _, role in embedder.calls] == ["query", "passage"]
    assert len(embedder.calls[0][0]) == 2
    assert len(embedder.calls[1][0]) == 2
    assert all("Source" not in text for text in embedder.calls[0][0])


def test_sentences_without_valid_citations_do_not_trigger_embeddings():
    embedder = StubEmbedder()

    checks = check_citation_support(
        "No citation. Invalid label [Source 2].",
        [{"text": "Only source."}],
        embedder,
        threshold=0.5,
    )

    assert checks == []
    assert embedder.calls == []


def test_sentence_indexes_ignore_hidden_markdown_link_destinations():
    embedder = StubEmbedder()

    checks = check_citation_support(
        "See [the docs](https://example.com/a_(b).pdf). Claim [Source 1].",
        [{"text": "A passage about the claim."}],
        embedder,
        threshold=0.5,
    )

    assert checks[0]["sentence_index"] == 1
    assert "https://example.com" not in embedder.calls[0][0][0]


def test_embedding_uses_visible_markdown_link_text_without_its_destination():
    embedder = StubEmbedder()

    checks = check_citation_support(
        "See [the docs](https://example.com) [Source 1].",
        [{"text": "The docs explain the claim."}],
        embedder,
        threshold=0.5,
    )

    assert checks[0]["sentence_index"] == 0
    assert "the docs" in embedder.calls[0][0][0]
    assert "https://example.com" not in embedder.calls[0][0][0]


def test_threshold_uses_full_precision_before_rounding_the_display_score():
    class NearThresholdEmbedder:
        def generate_embedding(self, texts, role):
            if role == "query":
                return np.array([[1.0, 0.0]])
            return np.array([[0.50004, (1 - 0.50004**2) ** 0.5]])

    checks = check_citation_support(
        "Claim [Source 1].",
        [{"text": "Passage."}],
        NearThresholdEmbedder(),
        threshold=0.50001,
    )

    assert checks == [{
        "sentence_index": 0,
        "cited_labels": [1],
        "score": 0.5,
        "supported": True,
    }]
