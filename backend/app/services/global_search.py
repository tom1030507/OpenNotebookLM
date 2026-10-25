"""Rank source passages across projects visible to one account."""
from time import perf_counter
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.db.models import Document, Project, User
from app.routers.ownership import visible_projects
from app.schemas import (
    ProjectSearchDocument,
    ProjectSearchPassage,
    ProjectSearchProject,
    ProjectSearchResponse,
)
from app.services.projects import ProjectService

logger = structlog.get_logger()
PROJECT_SEARCH_TOP_K = 30


def search_visible_projects(
    db: Session,
    user: User,
    rag_service: Any,
    query: str,
) -> ProjectSearchResponse:
    """Search and group passages from source links in visible projects.

    Args:
        db: Database session used to resolve project and source access.
        user: Signed-in account making the search.
        rag_service: Existing hybrid retrieval service.
        query: Non-blank search text.

    Returns:
        Ranked passages grouped by visible project and source document.
    """
    started = perf_counter()
    visible_project_ids = visible_projects(db, user).with_entities(Project.id)
    rows = (
        ProjectService.project_document_query(db)
        .filter(
            Project.id.in_(visible_project_ids),
            Document.status == "ready",
        )
        .with_entities(
            Project.id,
            Project.name,
            Document.id,
            Document.title,
            Document.source_type,
        )
        .distinct()
        .all()
    )

    project_names = {}
    documents = {}
    project_ids_by_document = {}
    for project_id, project_name, document_id, title, source_type in rows:
        project_names[project_id] = project_name
        documents[document_id] = (title or "Untitled source", source_type)
        project_ids_by_document.setdefault(document_id, []).append(project_id)

    if not documents:
        return ProjectSearchResponse(projects=[])

    chunks, _diagnostics = rag_service.retrieve_with_diagnostics(
        db=db,
        query=query,
        top_k=PROJECT_SEARCH_TOP_K,
        allowed_document_ids=sorted(documents),
    )

    grouped = {}
    for chunk in chunks:
        document_id = chunk.get("document_id")
        document = documents.get(document_id)
        if document is None:
            # Keep the authorization boundary even if a retrieval adapter returns
            # a stale or out-of-scope candidate.
            continue

        title, source_type = document
        metadata = chunk.get("metadata") or {}
        passage = ProjectSearchPassage(
            chunk_id=chunk["chunk_id"],
            text=chunk["text"],
            score=chunk["score"],
            page_num=metadata.get("page_num"),
            section=metadata.get("section") or metadata.get("heading_path"),
        )
        for project_id in project_ids_by_document[document_id]:
            project = grouped.setdefault(project_id, {})
            source = project.setdefault(document_id, {
                "title": title,
                "source_type": source_type,
                "passages": [],
            })
            source["passages"].append(passage)

    response = ProjectSearchResponse(projects=[
        ProjectSearchProject(
            project_id=project_id,
            project_name=project_names[project_id],
            documents=[
                ProjectSearchDocument(
                    document_id=document_id,
                    title=source["title"],
                    source_type=source["source_type"],
                    passages=source["passages"],
                )
                for document_id, source in grouped[project_id].items()
            ],
        )
        for project_id in grouped
    ])
    logger.info(
        "Cross-project search completed",
        visible_projects=len(project_names),
        source_documents=len(documents),
        passages=sum(
            len(source["passages"])
            for project in grouped.values()
            for source in project.values()
        ),
        latency_ms=round((perf_counter() - started) * 1000, 2),
    )
    return response
