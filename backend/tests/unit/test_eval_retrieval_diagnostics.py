"""The eval harness records performance without loading the ML stack."""
from dataclasses import dataclass
from types import ModuleType
import sys

from sqlalchemy import inspect, text

from scripts import eval_retrieval


class _FakeRag:
    """Return one deterministic result plus request-local diagnostics."""

    def retrieve_with_diagnostics(self, **kwargs):
        """Return the frozen diagnostics interface used by the harness."""
        return ([{
            "document_id": "document-1",
            "text": "the answer-bearing passage",
            "score": 0.75,
        }], {
            "dense_candidates": 8,
            "lexical_candidates": 3,
            "fused_candidates": 9,
            "latency_ms": 9.0,
            "active_backend": "sqlitevec",
        })


def test_run_queries_records_latency_and_candidate_counts(monkeypatch):
    """Every query row carries measured latency and all candidate pool sizes."""
    fake_rag_module = ModuleType("app.services.rag")
    fake_rag_module.RAGService = _FakeRag
    monkeypatch.setitem(sys.modules, "app.services.rag", fake_rag_module)

    ticks = iter((100.0, 100.0125))
    monkeypatch.setattr(eval_retrieval, "perf_counter", lambda: next(ticks))

    results = eval_retrieval.run_queries(
        db=object(),
        queries=[{
            "id": "q1",
            "lang": "en",
            "mode": "direct",
            "query": "where is the answer?",
            "expect_docs": ["source-1"],
            "must_contain": ["answer-bearing"],
        }],
        doc_ids={"source-1": "document-1"},
        project_id="project-1",
    )

    assert results[0]["latency_ms"] == 12.5
    assert results[0]["dense_candidates"] == 8
    assert results[0]["lexical_candidates"] == 3
    assert results[0]["fused_candidates"] == 9
    assert results[0]["active_backend"] == "sqlitevec"


@dataclass
class _IndexStatus:
    """Status stand-in proving the eval accepts dataclass results."""

    active_backend: str = "sqlitevec"
    canonical_chunks: int = 12
    dense_rows: int = 12
    lexical_rows: int = 12


def test_normalize_index_report_accepts_dataclass():
    """Eval output serializes the core service's public status value."""
    report = eval_retrieval.normalize_index_report(_IndexStatus())
    assert report == {
        "active_backend": "sqlitevec",
        "canonical_chunks": 12,
        "dense_rows": 12,
        "lexical_rows": 12,
    }


def test_eval_database_uses_core_schema_and_connection_policy(tmp_path):
    """The disposable eval index has the same invariants as the app database."""
    session, engine = eval_retrieval.build_session(tmp_path / "eval.db")
    try:
        assert "chunks" in inspect(engine).get_table_names()
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert session.execute(text("PRAGMA busy_timeout")).scalar_one() >= 5000
    finally:
        session.close()
        engine.dispose()


def test_write_report_includes_index_and_latency_sections(tmp_path):
    """The Markdown artifact exposes backend/shape and aggregate performance."""
    payload = {
        "tag": "indexed",
        "run_at": "2026-08-24T01:02:03+00:00",
        "corpus_size": 1,
        "query_count": 1,
        "settings": {"eval_top_k": 10},
        "metrics": {
            "overall": {
                "queries": 1,
                "recall_at_1": 1.0,
                "recall_at_3": 1.0,
                "recall_at_5": 1.0,
                "recall_at_10": 1.0,
                "precision_at_5": 1.0,
                "mrr_at_10": 1.0,
            }
        },
        "index_health": {"chunks": 1},
        "retrieval_index": {
            "active_backend": "sqlitevec",
            "canonical_chunks": 1,
            "dense_rows": 1,
            "lexical_rows": 1,
        },
        "retrieval_performance": {
            "latency_ms_p50": 12.5,
            "latency_ms_p95": 12.5,
            "dense_candidates_mean": 8.0,
            "lexical_candidates_mean": 3.0,
            "fused_candidates_mean": 9.0,
        },
        "retrieved_boilerplate_rate": 0.0,
        "retrieved_citation_rate": 0.0,
        "results": [{
            "id": "q1",
            "lang": "en",
            "mode": "direct",
            "query": "question",
            "expect_docs": ["source-1"],
            "first_hit_rank": 1,
            "latency_ms": 12.5,
            "dense_candidates": 8,
            "lexical_candidates": 3,
            "fused_candidates": 9,
        }],
    }

    eval_retrieval.write_report(tmp_path, payload)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## Retrieval index" in report
    assert "active_backend" in report
    assert "## Retrieval performance" in report
    assert "latency_ms_p95" in report
    assert "Dense candidates" in report
