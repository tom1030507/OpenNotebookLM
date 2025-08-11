"""Export service for converting conversations and projects to various formats."""
import json
import os
import tempfile
import zipfile
from datetime import datetime
from typing import Optional, Tuple, Any, Dict, List
from sqlalchemy.orm import Session
import structlog

from app.db.models import Project, Conversation, Message, Document, Chunk

logger = structlog.get_logger()


class ExportService:
    """Service for exporting data in various formats."""
    
    def export_conversation(
        self,
        db: Session,
        conversation: Conversation,
        format: str = "markdown",
        include_citations: bool = True
    ) -> Tuple[str, str, str]:
        """Export a conversation to specified format.
        
        Returns: (content, content_type, filename)
        """
        if format == "markdown":
            return self._export_conversation_markdown(conversation, include_citations)
        elif format == "json":
            return self._export_conversation_json(conversation, include_citations)
        elif format == "txt":
            return self._export_conversation_text(conversation, include_citations)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _export_conversation_markdown(
        self, 
        conversation: Conversation,
        include_citations: bool
    ) -> Tuple[str, str, str]:
        """Export conversation as Markdown."""
        content = f"# {conversation.title or 'Untitled Conversation'}\n\n"
        content += f"**Created**: {conversation.created_at}\n"
        content += f"**Updated**: {conversation.updated_at}\n\n"
        content += "---\n\n"
        
        for message in conversation.messages:
            # Add role header
            if message.role == "user":
                content += f"## 👤 User\n\n"
            else:
                content += f"## 🤖 Assistant\n\n"
            
            # Add message text
            content += f"{message.text}\n\n"
            
            # Add citations if requested
            if include_citations and message.citations_json:
                citations = message.citations_json
                if citations:
                    content += "**Sources:**\n"
                    for citation in citations:
                        content += f"- {citation.get('document_title', 'Unknown')}"
                        if citation.get('chunk_index'):
                            content += f" (Chunk {citation['chunk_index']})"
                        content += "\n"
                    content += "\n"
            
            content += "---\n\n"
        
        filename = f"conversation_{conversation.id}_{datetime.now().strftime('%Y%m%d')}.md"
        return content, "text/markdown", filename
    
    def _export_conversation_json(
        self,
        conversation: Conversation,
        include_citations: bool
    ) -> Tuple[str, str, str]:
        """Export conversation as JSON."""
        data = {
            "id": conversation.id,
            "title": conversation.title,
            "project_id": conversation.project_id,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "messages": []
        }
        
        for message in conversation.messages:
            msg_data = {
                "id": message.id,
                "role": message.role,
                "text": message.text,
                "created_at": message.created_at.isoformat()
            }
            
            if include_citations and message.citations_json:
                msg_data["citations"] = message.citations_json
            
            data["messages"].append(msg_data)
        
        content = json.dumps(data, indent=2, ensure_ascii=False)
        filename = f"conversation_{conversation.id}_{datetime.now().strftime('%Y%m%d')}.json"
        return content, "application/json", filename
    
    def _export_conversation_text(
        self,
        conversation: Conversation,
        include_citations: bool
    ) -> Tuple[str, str, str]:
        """Export conversation as plain text."""
        content = f"{conversation.title or 'Untitled Conversation'}\n"
        content += "=" * 50 + "\n\n"
        
        for message in conversation.messages:
            role = "USER" if message.role == "user" else "ASSISTANT"
            content += f"[{role}]:\n{message.text}\n\n"
            
            if include_citations and message.citations_json:
                citations = message.citations_json
                if citations:
                    content += "Sources: "
                    sources = [c.get('document_title', 'Unknown') for c in citations]
                    content += ", ".join(sources) + "\n\n"
            
            content += "-" * 30 + "\n\n"
        
        filename = f"conversation_{conversation.id}_{datetime.now().strftime('%Y%m%d')}.txt"
        return content, "text/plain", filename
    
    def export_project(
        self,
        db: Session,
        project: Project,
        format: str = "json",
        include_documents: bool = True,
        include_conversations: bool = True
    ) -> Tuple[str, str, str]:
        """Export an entire project."""
        if format == "json":
            return self._export_project_json(
                db, project, include_documents, include_conversations
            )
        elif format == "markdown":
            return self._export_project_markdown(
                db, project, include_documents, include_conversations
            )
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _export_project_json(
        self,
        db: Session,
        project: Project,
        include_documents: bool,
        include_conversations: bool
    ) -> Tuple[str, str, str]:
        """Export project as JSON."""
        data = {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
            "meta": project.meta_json
        }
        
        if include_documents:
            data["documents"] = []
            # Get documents through relationships
            documents = db.query(Document).join(
                Document.projects
            ).filter(
                Project.id == project.id
            ).all()
            
            for doc in documents:
                doc_data = {
                    "id": doc.id,
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "source_url": doc.source_url,
                    "status": doc.status,
                    "chunk_count": len(doc.chunks) if doc.chunks else 0
                }
                data["documents"].append(doc_data)
        
        if include_conversations:
            data["conversations"] = []
            conversations = db.query(Conversation).filter(
                Conversation.project_id == project.id
            ).all()
            
            for conv in conversations:
                conv_data = {
                    "id": conv.id,
                    "title": conv.title,
                    "message_count": len(conv.messages),
                    "created_at": conv.created_at.isoformat()
                }
                data["conversations"].append(conv_data)
        
        content = json.dumps(data, indent=2, ensure_ascii=False)
        filename = f"project_{project.id}_{datetime.now().strftime('%Y%m%d')}.json"
        return content, "application/json", filename
    
    def _export_project_markdown(
        self,
        db: Session,
        project: Project,
        include_documents: bool,
        include_conversations: bool
    ) -> Tuple[str, str, str]:
        """Export project as Markdown."""
        content = f"# {project.name}\n\n"
        
        if project.description:
            content += f"## Description\n{project.description}\n\n"
        
        content += f"**Created**: {project.created_at}\n"
        content += f"**Updated**: {project.updated_at}\n\n"
        
        if include_documents:
            content += "## Documents\n\n"
            # Get documents through relationships
            documents = db.query(Document).join(
                Document.projects
            ).filter(
                Project.id == project.id
            ).all()
            
            for doc in documents:
                content += f"### {doc.title}\n"
                content += f"- Type: {doc.source_type}\n"
                content += f"- Status: {doc.status}\n"
                if doc.source_url:
                    content += f"- Source: {doc.source_url}\n"
                content += f"- Chunks: {len(doc.chunks) if doc.chunks else 0}\n\n"
        
        if include_conversations:
            content += "## Conversations\n\n"
            conversations = db.query(Conversation).filter(
                Conversation.project_id == project.id
            ).all()
            
            for conv in conversations:
                content += f"### {conv.title or 'Untitled'}\n"
                content += f"- Messages: {len(conv.messages)}\n"
                content += f"- Created: {conv.created_at}\n\n"
        
        filename = f"project_{project.id}_{datetime.now().strftime('%Y%m%d')}.md"
        return content, "text/markdown", filename
    
    def generate_project_summary(
        self,
        db: Session,
        project: Project
    ) -> Dict[str, Any]:
        """Generate a summary of the project."""
        # Get document statistics
        documents = []
        total_chunks = 0
        
        # Get documents through relationships
        project_documents = db.query(Document).join(
            Document.projects
        ).filter(
            Project.id == project.id
        ).all()
        
        for doc in project_documents:
            chunk_count = len(doc.chunks) if doc.chunks else 0
            total_chunks += chunk_count
            
            documents.append({
                "id": doc.id,
                "title": doc.title,
                "source_type": doc.source_type,
                "source_url": doc.source_url,
                "status": doc.status,
                "chunk_count": chunk_count
            })
        
        # Get conversation statistics
        conversations = db.query(Conversation).filter(
            Conversation.project_id == project.id
        ).order_by(Conversation.updated_at.desc()).limit(5).all()
        
        recent_conversations = []
        total_messages = 0
        
        for conv in conversations:
            message_count = len(conv.messages)
            total_messages += message_count
            
            recent_conversations.append({
                "id": conv.id,
                "title": conv.title or "Untitled",
                "message_count": message_count,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat()
            })
        
        # Get total conversation count
        conversation_count = db.query(Conversation).filter(
            Conversation.project_id == project.id
        ).count()
        
        return {
            "project_id": project.id,
            "project_name": project.name,
            "document_count": len(documents),
            "total_chunks": total_chunks,
            "conversation_count": conversation_count,
            "total_messages": total_messages,
            "documents": documents,
            "recent_conversations": recent_conversations
        }
    
    def batch_export_conversations(
        self,
        db: Session,
        conversation_ids: List[str],
        format: str = "json"
    ) -> str:
        """Export multiple conversations to a ZIP file.
        
        Returns: Path to the created ZIP file
        """
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            exported_files = []
            
            for conv_id in conversation_ids:
                conversation = db.query(Conversation).filter(
                    Conversation.id == conv_id
                ).first()
                
                if not conversation:
                    logger.warning(f"Conversation {conv_id} not found")
                    continue
                
                # Export conversation
                content, _, filename = self.export_conversation(
                    db, conversation, format, include_citations=True
                )
                
                # Write to temp file
                file_path = os.path.join(temp_dir, filename)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                exported_files.append((file_path, filename))
            
            # Create ZIP file
            zip_path = tempfile.mktemp(suffix='.zip')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path, filename in exported_files:
                    zipf.write(file_path, filename)
            
            return zip_path
