"""Measure retrieval quality against a small fixed web corpus.

Run inside the backend container, which is the only environment with the ML
stack:

    python -m scripts.eval_retrieval --tag baseline

The run is self-contained: it builds its own SQLite database, ingests the corpus
through the real adapters, chunker and embedder, and queries through
`RAGService.retrieve_with_diagnostics`. It never touches `data/opennotebook.db`, and with
`LLM_MODE=none` it never calls a model provider.

Results land in `output/rag-eval/<tag>-<timestamp>/` as `metrics.json` plus a
readable `report.md`, so two runs can be diffed directly.
"""
import argparse
import asyncio
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, is_dataclass
import json
import os
import re
import sys
from time import perf_counter
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List

from sqlalchemy.orm import sessionmaker

from scripts import eval_corpus, eval_metrics
from scripts.reindex import apply_and_verify_backfill, unresolved_index_drift

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

# Only `backend/` is mounted into the container, so `REPO_ROOT` resolves to `/`
# there and the repo's `output/` convention is unreachable. Callers running in a
# container pass `--out` pointing at a mounted directory instead.
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "rag-eval"

# Deep enough to score Recall@10; the retriever's own candidate pool is wider.
EVAL_TOP_K = 10
SAFE_TAG_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class EvalLockError(RuntimeError):
    """A reusable eval database is already owned by another run."""


def safe_tag(value: str) -> str:
    """Validate a tag before using it in cache and report paths.

    Args:
        value: User-supplied run label.

    Returns:
        The unchanged safe label.

    Raises:
        argparse.ArgumentTypeError: If the tag contains separators, traversal,
            leading punctuation, or is unreasonably long.
    """
    if not SAFE_TAG_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "tag must start with a letter or digit and contain only letters, "
            "digits, dot, underscore, or hyphen (maximum 64 characters)"
        )
    return value


def index_database_path(cache_dir: Path, tag: str, reuse: bool) -> Path:
    """Choose a fixed reusable database or a unique per-run database.

    Args:
        cache_dir: Eval cache directory.
        tag: Validated run tag.
        reuse: Whether this run intentionally shares the tag's fixed database.

    Returns:
        Database path rooted directly under ``cache_dir``.
    """
    tag = safe_tag(tag)
    suffix = "" if reuse else "-" + uuid.uuid4().hex
    return cache_dir / ("index-%s%s.db" % (tag, suffix))


def output_target(output_root: Path, tag: str, run_time) -> Path:
    """Build a collision-resistant report directory path.

    Args:
        output_root: Parent directory selected by the caller.
        tag: Validated run tag.
        run_time: A UTC datetime for the report.

    Returns:
        Unique target using microseconds and a random UUID.
    """
    tag = safe_tag(tag)
    stamp = run_time.strftime("%Y%m%d-%H%M%S-%f")
    return output_root / ("%s-%s-%s" % (tag, stamp, uuid.uuid4().hex))


@contextmanager
def exclusive_eval_lock(lock_path: Path) -> Iterator[None]:
    """Hold a cross-platform O_EXCL file lock for one reusable eval run.

    Args:
        lock_path: Lock file adjacent to the fixed eval database.

    Returns:
        A context manager that yields while this process owns the lock file.

    Raises:
        EvalLockError: If another run already owns the tag.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            str(lock_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise EvalLockError(
            "reusable eval index is already in use: %s" % lock_path
        ) from exc

    try:
        os.write(descriptor, ("pid=%d\n" % os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def normalize_index_report(value: Any) -> Dict[str, Any]:
    """Turn a typed retrieval-index report into JSON-safe dictionary shape.

    Args:
        value: Mapping, dataclass, or value exposing ``as_dict``/``to_dict``.

    Returns:
        A shallow dictionary containing the report.

    Raises:
        TypeError: If the retrieval service violates its conversion contract.
    """
    if isinstance(value, Mapping):
        return dict(value)
    for method_name in ("as_dict", "to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            converted = method()
            if not isinstance(converted, Mapping):
                raise TypeError("%s() must return a mapping" % method_name)
            return dict(converted)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError("unsupported retrieval-index report: %r" % (type(value),))


def build_session(db_path: Path):
    """Create the database if needed and return a session bound to it.

    Args:
        db_path: Where the SQLite file goes.

    Returns:
        A tuple of (session, engine).
    """
    from app.db.database import create_database_engine, ensure_added_columns
    from app.db.models import Base

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine("sqlite:///" + db_path.as_posix(), echo=False)
    Base.metadata.create_all(bind=engine)
    ensure_added_columns(bind=engine)
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
        started_at = perf_counter()
        chunks, diagnostics_value = rag.retrieve_with_diagnostics(
            db=db, query=record["query"], project_id=project_id, top_k=EVAL_TOP_K
        )
        latency_ms = (perf_counter() - started_at) * 1000.0
        diagnostics = normalize_index_report(diagnostics_value)
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
            "latency_ms": round(latency_ms, 3),
            "dense_candidates": int(diagnostics.get("dense_candidates", 0)),
            "lexical_candidates": int(diagnostics.get("lexical_candidates", 0)),
            "fused_candidates": int(diagnostics.get("fused_candidates", len(chunks))),
            "active_backend": diagnostics.get("active_backend", "unknown"),
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
        print("  %-6s %s/%-5s %-6s retrieved=%d candidates=%d/%d/%d %.1fms" % (
            record["id"], record["lang"], record["mode"], marker, len(chunks),
            diagnostics.get("dense_candidates", 0),
            diagnostics.get("lexical_candidates", 0),
            diagnostics.get("fused_candidates", len(chunks)),
            latency_ms), flush=True)
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

    Returns:
        None.
    """
    # The caller gives every run a microsecond/UUID name, and exclusive creation
    # turns an astronomically unlikely collision into an error instead of an
    # overwrite of another process's evidence.
    target.mkdir(parents=True, exist_ok=False)
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
        "## Retrieval index",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for key, value in payload["retrieval_index"].items():
        lines.append("| `%s` | %s |" % (key, "-" if value is None else value))
    lines += [
        "",
        "## Retrieval performance",
        "",
        "Times are measured around retrieval with `perf_counter`; candidate counts are",
        "reported by the same request, not process-global counters.",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for key, value in payload["retrieval_performance"].items():
        formatted = "%.3f" % value if isinstance(value, float) else str(value)
        lines.append("| `%s` | %s |" % (key, formatted))
    lines += [
        "",
        "| Query | Latency ms | Dense candidates | Lexical candidates | Fused candidates | Backend |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for record in payload["results"]:
        lines.append("| %s | %.3f | %d | %d | %d | %s |" % (
            record["id"], record["latency_ms"], record["dense_candidates"],
            record["lexical_candidates"], record["fused_candidates"],
            record.get("active_backend", "unknown")))
    lines += [
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


def run_evaluation(args, output_root: Path) -> int:
    """Execute one fully isolated or exclusively locked eval run.

    Args:
        args: Parsed CLI arguments.
        output_root: Parent directory for report artifacts.

    Returns:
        Process exit code.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dataset = eval_corpus.load_dataset()
    corpus, queries = dataset["corpus"], dataset["queries"]

    fetched = eval_corpus.fetch_into_cache(corpus, refresh=args.refresh_cache)
    print("corpus cache: %d pages (%d fetched now)" % (len(corpus), len(fetched)), flush=True)

    index_db = index_database_path(
        eval_corpus.CACHE_DIR,
        args.tag,
        reuse=args.reuse_index,
    )
    project_id = "eval-project"
    reused = args.reuse_index and index_db.exists()
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

        # Lifecycle hooks normally keep both indexes aligned. Backfill here is
        # an idempotent guard for reused eval databases and makes the active
        # index shape part of the measurement rather than an assumption.
        from app.services.retrieval_index import get_retrieval_index

        retrieval_index = get_retrieval_index()
        index_changes, index_audit, retrieval_index_status = apply_and_verify_backfill(
            retrieval_index,
            session,
            engine,
            document_ids=list(doc_ids.values()),
        )
        print("index reconciliation: added=%s updated=%s removed=%s" % (
            index_changes.get("added", 0), index_changes.get("updated", 0),
            index_changes.get("removed", 0)), flush=True)
        unresolved = unresolved_index_drift(index_audit)
        if unresolved:
            raise RuntimeError("retrieval index remains inconsistent after backfill: %s" % (
                ", ".join("%s=%d" % item for item in sorted(unresolved.items()))
            ))

        chunks = session.query(Chunk).all()
        settings_snapshot = snapshot_settings()
        health = eval_metrics.index_health(
            [chunk.text for chunk in chunks],
            settings_snapshot["chunk_size"],
            [chunk.heading_path for chunk in chunks],
        )

        print("querying:", flush=True)
        results = run_queries(session, queries, doc_ids, project_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()

    from app.utils.time import utc_now

    run_time = utc_now()
    payload = {
        "tag": args.tag,
        "run_at": run_time.isoformat(timespec="seconds"),
        "corpus_size": len(corpus),
        "query_count": len(queries),
        "settings": settings_snapshot,
        "metrics": group_metrics(results),
        "index_health": health,
        "retrieval_index": retrieval_index_status,
        "retrieval_performance": eval_metrics.retrieval_performance(results),
        "retrieved_boilerplate_rate": retrieved_share(results, "boilerplate_ranks"),
        "retrieved_citation_rate": retrieved_share(results, "citation_ranks"),
        "results": results,
    }

    target = output_target(output_root, args.tag, run_time)
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
    performance = payload["retrieval_performance"]
    print("retrieval latency ms p50/p95/max %.1f/%.1f/%.1f  candidates dense/lexical/fused %.1f/%.1f/%.1f" % (
        performance["latency_ms_p50"], performance["latency_ms_p95"],
        performance["latency_ms_max"], performance["dense_candidates_mean"],
        performance["lexical_candidates_mean"], performance["fused_candidates_mean"]))
    print("backend %s  canonical/dense/lexical %s/%s/%s" % (
        retrieval_index_status.get("active_backend", "unknown"),
        retrieval_index_status.get("canonical_chunks", "?"),
        retrieval_index_status.get("dense_rows", "?"),
        retrieval_index_status.get("lexical_rows", "?")))
    print("report: %s" % target)
    return 0


def main(argv=None) -> int:
    """Parse arguments, acquire any reuse lock, and run the evaluation.

    Args:
        argv: Optional argument list, for testing.

    Returns:
        Process exit code; 2 means a reusable index is already locked.
    """
    parser = argparse.ArgumentParser(description="Measure RAG retrieval quality.")
    parser.add_argument("--tag", default="run", type=safe_tag,
                        help="safe label for cache and output paths")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="re-fetch the corpus pages over the network")
    parser.add_argument("--reuse-index", action="store_true",
                        help="use/create this tag's fixed index under an exclusive lock; "
                             "only safe when extraction and chunking are unchanged")
    parser.add_argument("--out", default=None,
                        help="directory for run reports; required in the container, "
                             "where the repo root is not mounted")
    args = parser.parse_args(argv)

    output_root = Path(args.out) if args.out else DEFAULT_OUTPUT_ROOT
    lock_context = (
        exclusive_eval_lock(eval_corpus.CACHE_DIR / ("index-%s.lock" % args.tag))
        if args.reuse_index
        else nullcontext()
    )
    try:
        with lock_context:
            return run_evaluation(args, output_root)
    except EvalLockError as exc:
        print("eval error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
