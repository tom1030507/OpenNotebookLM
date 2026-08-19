"""Tests for the asymmetric query/passage prefixes some embedding models need."""
import pytest

from app.services import embeddings as embeddings_module
from app.services.embeddings import prefix_for_role


@pytest.fixture
def model_name(monkeypatch):
    """Set the configured embedding model for one test."""
    def _set(name):
        monkeypatch.setattr(embeddings_module.settings, "emb_model_name", name)
    return _set


def test_e5_models_get_asymmetric_prefixes(model_name):
    model_name("intfloat/multilingual-e5-base")

    assert prefix_for_role("query") == "query: "
    assert prefix_for_role("passage") == "passage: "
    # The two must differ, or the asymmetry the model was trained on is lost.
    assert prefix_for_role("query") != prefix_for_role("passage")


def test_non_e5_models_get_no_prefix(model_name):
    for name in ("BAAI/bge-m3", "BAAI/bge-small-en-v1.5",
                 "sentence-transformers/all-MiniLM-L6-v2"):
        model_name(name)
        assert prefix_for_role("query") == ""
        assert prefix_for_role("passage") == ""


def test_unknown_role_is_not_prefixed(model_name):
    model_name("intfloat/multilingual-e5-base")

    # Better to embed without a prefix than with an invented one.
    assert prefix_for_role("something-else") == ""
