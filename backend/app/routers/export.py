"""Export router for exporting conversations and projects."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, FileResponse
from sqlalchemy.orm import Session
import structlog
import json
import tempfile
import os

from app.db.database import get_db
from app.db.models import Project, Conversation, Message, Document, User
from app.services.export import ExportService
from app.utils.time import utc_now
from app.routers.auth import get_current_user
from app.routers.ownership import require_conversation, require_project

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()

# Initialize export service
export_service = ExportService()


@router.get("/export/conversation/{conversation_id}")
async def export_conversation(
    conversation_id: str,
    format: str = "markdown",
    include_citations: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export one of the caller's conversations to various formats.
    
    Supported formats: markdown, json, txt
    """
    # Validate format
    if format not in ["markdown", "json", "txt"]:
        raise HTTPException(status_code=400, detail="Invalid export format")
    
    conversation = require_conversation(db, conversation_id, current_user)
    
    try:
        # Export conversation
        content, content_type, filename = export_service.export_conversation(
            db=db,
            conversation=conversation,
            format=format,
            include_citations=include_citations
        )
        
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/project/{project_id}")
async def export_project(
    project_id: str,
    format: str = "json",
    include_documents: bool = True,
    include_conversations: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export one of the caller's projects in full.
    
    Includes all documents, conversations, and metadata.
    """
    # Validate format
    if format not in ["json", "markdown"]:
        raise HTTPException(status_code=400, detail="Invalid export format")
    
    project = require_project(db, project_id, current_user)
    
    try:
        # Export project
        content, content_type, filename = export_service.export_project(
            db=db,
            project=project,
            format=format,
            include_documents=include_documents,
            include_conversations=include_conversations
        )
        
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        logger.error(f"Project export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/project/{project_id}/summary")
async def export_project_summary(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate and export a summary report of one of the caller's projects.
    
    Includes statistics, key insights, and document overview.
    """
    project = require_project(db, project_id, current_user)
    
    try:
        # Generate summary
        summary = export_service.generate_project_summary(db, project)
        
        # Create markdown report
        report = f"""# Project Summary: {project.name}

**Generated**: {utc_now().isoformat()}

## Overview
{project.description or 'No description provided.'}

## Statistics
- **Documents**: {summary['document_count']}
- **Total Chunks**: {summary['total_chunks']}
- **Conversations**: {summary['conversation_count']}
- **Total Messages**: {summary['total_messages']}

## Documents
"""
        
        for doc in summary['documents']:
            report += f"\n### {doc['title']}\n"
            report += f"- Type: {doc['source_type']}\n"
            report += f"- Chunks: {doc['chunk_count']}\n"
            report += f"- Status: {doc['status']}\n"
            if doc.get('source_url'):
                report += f"- Source: {doc['source_url']}\n"
        
        if summary['recent_conversations']:
            report += "\n## Recent Conversations\n"
            for conv in summary['recent_conversations']:
                report += f"\n### {conv['title']}\n"
                report += f"- Messages: {conv['message_count']}\n"
                report += f"- Created: {conv['created_at']}\n"
        
        return Response(
            content=report,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=project_{project_id}_summary.md"
            }
        )
        
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export/batch")
async def batch_export(
    conversation_ids: list[str],
    format: str = "json",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export several of the caller's conversations at once.
    
    Returns a ZIP file containing all exports.
    """
    if not conversation_ids:
        raise HTTPException(status_code=400, detail="No conversation IDs provided")
    
    if format not in ["markdown", "json", "txt"]:
        raise HTTPException(status_code=400, detail="Invalid export format")
    
    # Every id is checked before any of them is exported, so a batch cannot be
    # used to smuggle one other account's conversation in among your own.
    for conversation_id in conversation_ids:
        require_conversation(db, conversation_id, current_user)
    
    try:
        # Create temporary file for ZIP
        zip_path = export_service.batch_export_conversations(
            db=db,
            conversation_ids=conversation_ids,
            format=format
        )
        
        if not zip_path or not os.path.exists(zip_path):
            raise HTTPException(status_code=500, detail="Export failed")
        
        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=f"conversations_export_{utc_now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        
    except Exception as e:
        logger.error(f"Batch export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
