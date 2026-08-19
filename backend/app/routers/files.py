"""Router that serves the file stored for a single document."""
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.db.models import User
from app.services.document_files import resolve_stored_file
from app.routers.auth import get_current_user
from app.routers.ownership import require_document

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()


def _inline_disposition(filename: str) -> str:
    """Build a Content-Disposition header that previews rather than downloads.

    Args:
        filename: Name to suggest if the viewer does save the file

    Returns:
        An ``inline`` header value, using the RFC 5987 form when the name
        cannot be written literally
    """
    encoded = quote(filename, safe="")
    if encoded == filename:
        return f'inline; filename="{filename}"'

    return f"inline; filename*=utf-8''{encoded}"


@router.get("/docs/{doc_id}/file")
async def get_document_file(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Serve the file behind one of the caller's documents.

    Only uploaded documents have a file. URL and YouTube sources keep an
    external address in ``source_url``, which is served by nobody here.

    This route returns raw bytes, so it needs the ownership check as much as any
    other: a signed-in caller who guessed a document id could otherwise download
    another account's upload in full.
    """
    document = require_document(db, doc_id, current_user)

    file_path = resolve_stored_file(document.source_url)

    if not file_path:
        logger.info("Document has no file to serve", doc_id=doc_id)
        raise HTTPException(status_code=404, detail="Document has no stored file")

    # The stored name is prefixed with the document id; the original filename
    # is nicer to show, but the type comes from the file we are actually
    # serving rather than from anything a client chose.
    original_name = (document.meta_json or {}).get("filename")
    display_name = (
        original_name
        if isinstance(original_name, str) and original_name
        else file_path.name
    )
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    return FileResponse(
        file_path,
        media_type=media_type,
        headers={"Content-Disposition": _inline_disposition(display_name)},
    )
