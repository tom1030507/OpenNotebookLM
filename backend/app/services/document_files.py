"""Access to the files stored for uploaded documents.

The uploads directory is deliberately not mounted as static files: a guessed
filename must not be enough to read one. Every read goes through
:func:`resolve_stored_file`, which only hands back a path that really does live
inside the uploads directory.
"""
from pathlib import Path
from typing import Optional

# Uploaded files live here, relative to the process working directory.
UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def resolve_stored_file(stored_path: Optional[str]) -> Optional[Path]:
    """Resolve a document's stored path to a readable file inside uploads.

    Args:
        stored_path: The document's ``source_url``. For an upload this is the
            path the file was written to; for a URL or YouTube source it is an
            external address and never a file on this disk.

    Returns:
        The resolved file, or None when there is nothing this route may serve:
        no path at all, a path that leaves the uploads directory (``..``
        segments, an absolute path elsewhere, a symlink pointing out), or a
        path with no file behind it.
    """
    if not stored_path:
        return None

    try:
        uploads_root = UPLOAD_DIR.resolve()
        candidate = Path(stored_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate

        # resolve() collapses ".." and follows symlinks, so the containment
        # check below sees where the path really ends up.
        resolved = candidate.resolve()
        if not resolved.is_relative_to(uploads_root):
            return None

        if not resolved.is_file():
            return None
    except OSError:
        # A stored value that is not a usable path at all (an external URL on
        # Windows, say) is simply not a file we serve.
        return None

    return resolved
