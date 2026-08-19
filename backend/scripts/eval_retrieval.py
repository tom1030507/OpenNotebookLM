"""Measure retrieval quality against a small fixed web corpus.

Run inside the backend container, which is the only environment with the ML
stack:

    python -m scripts.eval_retrieval --tag baseline

The run is self-contained: it builds its own SQLite database, ingests the corpus
through the real adapters, chunker and embedder, and queries through
`RAGService._retrieve_chunks`. It never touches `data/opennotebook.db`, and with
`LLM_MODE=none` it never calls a model provider.

Results land in `output/rag-eval/<tag>-<timestamp>/` as `metrics.json` plus a
readable `report.md`, so two runs can be diffed directly.
"""
import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scripts import eval_corpus, eval_metrics

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

# Only `backend/` is mounted into the container, so `REPO_ROOT` resolves to `/`
# there and the repo's `output/` convention is unreachable. Callers running in a
# container pass `--out` pointing at a mounted directory instead.
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "rag-eval"

# Deep enough to score Recall@10; the retriever's own candidate pool is wider.
EVAL_TOP_K = 10


def build_session(db_path: Path):
    """Create the database if needed and return a session bound to it.

    Args:
        db_path: Where the SQLite file goes.

    Returns:
        A tuple of (session, engine).
    """
    from app.db.models import Base

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        "sqlite:///" + db_path.as_posix(),
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    return session, engine


def ingest_corpus(db, entries: List[Dict[str, Any]], project_id: str) -> Dict[str, str]:
    """Ingest every corpus entry through the real pipeline.

    Mirrors `DocumentService.process_url` without its fire-and-forget
    `create_task`, so indexing has finished by the time this returns.

    Args:
        db: Database session.
        entries: Corpus entries with `id` and `url`.
        project_id: Project to attach the documents to.

    Returns:
        Corpus entry id to the document id it became.
    """
    from app.db.models import Document, Project, ProjectDocument
    from app.services.documents import DocumentService
    from app.utils.time import utc_now_iso

    service = DocumentService()
    db.add(Project(id=project_id, name="RAG eval", meta_json={}))
    db.commit()

    doc_ids: Dict[str, str] = {}
    with eval_corpus.serve_from_cache(entries):
        for entry in entries:
            doc_id = str(uuid.uuid4())
            db.add(Document(
                id=doc_id,
                title=entry["url"],
                source_type="url",
                source_url=entry["url"],
                status="queued",
                meta_json={"url": entry["url"], "upload_time": utc_now_iso()},
            ))
            db.add(ProjectDocument(project_id=project_id, document_id=doc_id))
            db.commit()

            asyncio.run(service._process_url_async(db, doc_id, entry["url"]))

            document = db.query(Document).filter(Document.id == doc_id).first()
            print("  %-16s %-10s chars=%7d error=%s" % (
                entry["id"], document.status, len(document.content or ""),
                document.error_message or "-"), flush=True)
            doc_ids[entry["id"]] = doc_id
    return doc_ids


def snapshot_settings() -> Dict[str, Any]:
    """Record the knobs that shape retrieval, so a report explains itself.

    Returns:
        Setting name to value.
    """
    from app.config import get_settings

    settings = get_settings()
    return {
        "emb_model_name": settings.emb_model_name,
        "emb_dimension": settings.emb_dimension,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_enabled": settings.rerank_enabled,
        "rerank_alpha": settings.rerank_alpha,
        "rerank_beta": settings.rerank_beta,
        "rerank_gamma": settings.rerank_gamma,
        "llm_mode": settings.llm_mode,
        "eval_top_k": EVAL_TOP_K,
    }


def run_queries(db, queries, doc_ids, project_id):
    """Retrieve for every query and judge each hit.

    Args:
        db: Database session.
        queries: Dataset query records.
        doc_ids: Corpus entry id to document id.
        project_id: Project scope for retrieval.

    Returns:
        A list of per-query result dicts.
    """
    from app.services.rag import RAGService

    rag = RAGService()
    results = []
    for record in queries:
        expected = {doc_ids[name] for name in record["expect_docs"] if name in doc_ids}
        chunks = rag._retrieve_chunks(
            db=db, query=record["query"], project_id=project_id, top_k=EVAL_TOP_K
        )
        relevance = [
            chunk["document_id"] in expected
            and eval_metrics.judge(chunk["text"], record["must_contain"])
            for chunk in chunks
        ]
        first_hit = next((i for i, hit in enumerate(relevance, 1) if hit), None)
        results.append({
            "id": record["id"],
            "lang": record["lang"],
            "mode": record["mode"],
            "query": record["query"],
            "expect_docs": record["expect_docs"],
            "retrieved": len(chunks),
            "relevance": relevance,
            "first_hit_rank": first_hit,
            "boilerplate_ranks": [
                i for i, chunk in enumerate(chunks, 1)
                if eval_metrics.is_boilerplate(chunk["text"])
            ],
            "citation_ranks": [
                i for i, chunk in enumerate(chunks, 1)
                if eval_metrics.is_citation_like(chunk["text"])
            ],
            "top_chunks": [
                {
                    "rank": i,
                    "score": round(float(chunk.get("rerank_score", chunk["score"])), 4),
                    "document_id": chunk["document_id"],
                    "relevant": relevance[i - 1],
                    "preview": chunk["text"][:160],
                }
                for i, chunk in enumerate(chunks[:5], 1)
            ],
        })
        marker = ("HIT@%d" % first_hit) if first_hit else "MISS"
        print("  %-6s %s/%-5s %-6s retrieved=%d" % (
            record["id"], record["lang"], record["mode"], marker, len(chunks)), flush=True)
    return results


def group_metrics(results) -> Dict[str, Dict[str, float]]:
    """Summarise overall and per language/mode slice.

    Args:
        results: Per-query result dicts.

    Returns:
        Slice name to metric mapping.
    """
    groups = {"overall": results}
    for key in sorted({(r["lang"], r["mode"]) for r in results}):
        groups[key[0] + "/" + key[1]] = [
            r for r in results if (r["lang"], r["mode"]) == key
        ]
    return {
        name: eval_metrics.summarise({r["id"]: r["relevance"] for r in rows})
        for name, rows in groups.items()
    }


def retrieved_share(results, field: str) -> float:
    """Share of every retrieved chunk flagged under the given field.

    Args:
        results: Per-query result dicts.
        field: Either `boilerplate_ranks` or `citation_ranks`.

    Returns:
        Rate in [0, 1].
    """
    retrieved = sum(r["retrieved"] for r in results)
    flagged = sum(len(r[field]) for r in results)
    return flagged / retrieved if retrieved else 0.0


def write_report(target: Path, payload: Dict[str, Any]) -> None:
    """Write metrics.json and a readable report.md.

    Args:
        target: Run directory.
        payload: Everything the run produced.
    """
    target.mkdir(parents=True, exist_ok=True)
    (target / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    settings = payload["settings"]
    lines = [
        "# RAG retrieval eval - " + payload["tag"],
        "",
        "Run at %s against %d pages and %d questions, judged at ranks 1-%d." % (
            payload["run_at"], payload["corpus_size"], payload["query_count"],
            settings["eval_top_k"]),
        "",
        "## Settings",
        "",
        "| Setting | Value |",
        "|---|---|",
    ]
    lines += ["| `%s` | %s |" % (key, value) for key, value in settings.items()]
    lines += [
        "",
        "## Retrieval quality",
        "",
        "| Slice | Queries | R@1 | R@3 | R@5 | R@10 | P@5 | MRR@10 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, metrics in payload["metrics"].items():
        lines.append("| %s | %d | %.3f | %.3f | %.3f | %.3f | %.3f | %.3f |" % (
            name, metrics["queries"], metrics["recall_at_1"], metrics["recall_at_3"],
            metrics["recall_at_5"], metrics["recall_at_10"], metrics["precision_at_5"],
            metrics["mrr_at_10"]))
    lines += [
        "",
        "Recall@k is a hit rate: the share of questions with at least one",
        "answer-bearing chunk in the top k.",
        "",
        "## Index health",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for key, value in payload["index_health"].items():
        formatted = "%.3f" % value if isinstance(value, float) else str(value)
        lines.append("| `%s` | %s |" % (key, formatted))
    lines += [
        "",
        "Of the chunks actually retrieved: **%.3f** boilerplate, **%.3f** citation-like." % (
            payload["retrieved_boilerplate_rate"], payload["retrieved_citation_rate"]),
        "",
        "## Misses",
        "",
        "| Query | Lang/Mode | Expected | Question |",
        "|---|---|---|---|",
    ]
    misses = [r for r in payload["results"] if r["first_hit_rank"] is None]
    for record in misses:
        lines.append("| %s | %s/%s | %s | %s |" % (
            record["id"], record["lang"], record["mode"],
            ", ".join(record["expect_docs"]), record["query"]))
    if not misses:
        lines.append("| - | - | - | every question hit |")
    lines.append("")
    (target / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """Entry point.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Measure RAG retrieval quality.")
    parser.add_argument("--tag", default="run", help="label for the output directory")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="re-fetch the corpus pages over the network")
    parser.add_argument("--reuse-index", action="store_true",
                        help="keep a previously built index; only safe when neither "
                             "extraction nor chunking changed since it was built")
    parser.add_argument("--out", default=None,
                        help="directory for run reports; required in the container, "
                             "where the repo root is not mounted")
    args = parser.parse_args()

    output_root = Path(args.out) if args.out else DEFAULT_OUTPUT_ROOT

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dataset = eval_corpus.load_dataset()
    corpus, queries = dataset["corpus"], dataset["queries"]

    fetched = eval_corpus.fetch_into_cache(corpus, refresh=args.refresh_cache)
    print("corpus cache: %d pages (%d fetched now)" % (len(corpus), len(fetched)), flush=True)

    index_db = eval_corpus.CACHE_DIR / ("index-" + args.tag + ".db")
    project_id = "eval-project"
    if index_db.exists() and not args.reuse_index:
        index_db.unlink()

    reused = index_db.exists()
    session, engine = build_session(index_db)
    try:
        from app.db.models import Chunk, Document

        if reused:
            print("reusing existing index", flush=True)
            doc_ids = {}
            for entry in corpus:
                document = session.query(Document).filter(
                    Document.source_url == entry["url"]).first()
                if document:
                    doc_ids[entry["id"]] = document.id
        else:
            print("ingesting corpus through the real pipeline:", flush=True)
            doc_ids = ingest_corpus(session, corpus, project_id)

        chunks = session.query(Chunk).all()
        settings_snapshot = snapshot_settings()
        health = eval_metrics.index_health(
            [chunk.text for chunk in chunks],
            settings_snapshot["chunk_size"],
            [chunk.heading_path for chunk in chunks],
        )

        print("querying:", flush=True)
        results = run_queries(session, queries, doc_ids, project_id)
    finally:
        session.close()
        engine.dispose()

    payload = {
        "tag": args.tag,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "corpus_size": len(corpus),
        "query_count": len(queries),
        "settings": settings_snapshot,
        "metrics": group_metrics(results),
        "index_health": health,
        "retrieved_boilerplate_rate": retrieved_share(results, "boilerplate_ranks"),
        "retrieved_citation_rate": retrieved_share(results, "citation_ranks"),
        "results": results,
    }

    target = output_root / (args.tag + "-" + datetime.now().strftime("%Y%m%d-%H%M"))
    write_report(target, payload)

    overall = payload["metrics"]["overall"]
    print("")
    print("Recall@1 %.3f  Recall@5 %.3f  Recall@10 %.3f  MRR@10 %.3f" % (
        overall["recall_at_1"], overall["recall_at_5"],
        overall["recall_at_10"], overall["mrr_at_10"]))
    print("chunks %d  len p50/p95/max %.0f/%.0f/%.0f  oversize %.3f  heading_path %.3f" % (
        health["chunks"], health["len_p50"], health["len_p95"], health["len_max"],
        health["share_oversize_gt_2x"], health["share_with_heading_path"]))
    print("citation-like: index %.3f, retrieved %.3f   boilerplate: index %.3f, retrieved %.3f" % (
        health["share_citation_like"], payload["retrieved_citation_rate"],
        health["share_boilerplate"], payload["retrieved_boilerplate_rate"]))
    print("report: %s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
