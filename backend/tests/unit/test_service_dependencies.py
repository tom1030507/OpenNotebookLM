"""Tests for lazy, injectable document and RAG dependencies."""
import importlib
import subprocess
import sys
from types import ModuleType


class FalseyDouble:
    """A falsey dependency used to catch `value or Default()` regressions."""

    def __bool__(self):
        """Report false while remaining a valid dependency.

        Args:
            None.

        Returns:
            False.
        """
        return False


def test_service_modules_do_not_import_embeddings_for_injected_dependencies(monkeypatch):
    """Injected services must work when the ML module cannot be imported."""
    monkeypatch.delitem(sys.modules, "app.services.documents", raising=False)
    monkeypatch.delitem(sys.modules, "app.services.rag", raising=False)
    monkeypatch.setitem(sys.modules, "app.services.embeddings", None)

    documents = importlib.import_module("app.services.documents")
    rag = importlib.import_module("app.services.rag")
    embedding = FalseyDouble()
    chunking = FalseyDouble()
    llm = FalseyDouble()

    document_service = documents.DocumentService(
        chunking_service=chunking,
        embedding_service=embedding,
        pdf_adapter=FalseyDouble(),
        url_adapter=FalseyDouble(),
        youtube_adapter=FalseyDouble(),
    )
    rag_service = rag.RAGService(embedding_service=embedding, llm_service=llm)

    assert document_service.embedding_service is embedding
    assert document_service.chunking_service is chunking
    assert rag_service.embedding_service is embedding
    assert rag_service.llm_service is llm


def test_router_service_providers_are_lazy_cached_dependencies(monkeypatch):
    """Providers must construct once and remain addressable for overrides."""
    created = {"documents": 0, "rag": 0}

    class FakeDocumentService:
        def __init__(self):
            created["documents"] += 1

    class FakeRAGService:
        def __init__(self):
            created["rag"] += 1

    document_module = ModuleType("app.services.documents")
    document_module.DocumentService = FakeDocumentService
    rag_module = ModuleType("app.services.rag")
    rag_module.RAGService = FakeRAGService
    monkeypatch.setitem(sys.modules, "app.services.documents", document_module)
    monkeypatch.setitem(sys.modules, "app.services.rag", rag_module)

    from app.routers.ingest import get_document_service
    from app.routers.query import get_rag_service

    get_document_service.cache_clear()
    get_rag_service.cache_clear()
    try:
        assert get_document_service() is get_document_service()
        assert get_rag_service() is get_rag_service()
        assert created == {"documents": 1, "rag": 1}
    finally:
        get_document_service.cache_clear()
        get_rag_service.cache_clear()


def test_importing_routers_does_not_import_the_embedding_module():
    """A fresh router import must not cross the ML dependency boundary."""
    code = """
import sys
from app.config import Settings, get_settings
Settings.model_config["env_file"] = None
get_settings.cache_clear()
import app.routers.ingest
import app.routers.query
print("app.services.embeddings" in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "False"
