"""Give ownerless projects and documents an owner.

Rows written before per-user isolation existed have `user_id = NULL`. The API
treats a null owner as belonging to nobody rather than to everybody, which is the
safe default but means existing work is invisible until it is claimed. This is
how it gets claimed.

Only null owners are touched, so running it twice is harmless and it can never
move a row from one account to another.

    python -m scripts.assign_owner --username demo --dry-run
    python -m scripts.assign_owner --username demo

Conversations and messages have no owner column: `Conversation.project_id` is NOT
NULL, so they follow the project. Back up the database first.
"""
import argparse
import sys
from typing import List, Optional

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def build_session(database_url: str):
    """Open a session against the application's own database.

    Args:
        database_url: SQLAlchemy URL.

    Returns:
        A tuple of (session, engine).
    """
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        poolclass=StaticPool if database_url.startswith("sqlite") else None,
    )
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)(), engine


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point.

    Args:
        argv: Optional argument list, for testing.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Claim ownerless projects and documents.")
    parser.add_argument("--username", required=True,
                        help="account that will own the ownerless rows")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change and exit")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from app.config import get_settings
    from app.db.database import ensure_added_columns
    from app.db.models import Conversation, Document, Project, User

    database_url = get_settings().database_url
    db, engine = build_session(database_url)

    # In case this runs before the app has started against this database: the
    # ownership columns are added by init_db, and without them every query below
    # would fail on "no such column".
    added = ensure_added_columns(engine)
    if added:
        print("added missing columns: %s" % ", ".join(added))
    try:
        user = db.query(User).filter(User.username == args.username).first()
        if not user:
            existing = [row[0] for row in db.query(User.username).all()]
            print("No such account: %s. Accounts: %s" % (args.username, ", ".join(existing) or "none"))
            return 2

        unowned_projects = db.query(Project).filter(Project.user_id.is_(None)).all()
        unowned_documents = db.query(Document).filter(Document.user_id.is_(None)).all()
        following = db.query(func.count(Conversation.id)).filter(
            Conversation.project_id.in_([p.id for p in unowned_projects] or [""])
        ).scalar() or 0

        print("account: %s (%s)" % (user.username, user.id))
        print("ownerless projects:  %d" % len(unowned_projects))
        print("ownerless documents: %d" % len(unowned_documents))
        print("conversations that follow those projects: %d" % following)

        for project in unowned_projects:
            print("  project  %-40s %s" % ((project.name or "")[:38], project.id))
        for document in unowned_documents[:10]:
            print("  document %-40s %s" % ((document.title or "")[:38], document.id))
        if len(unowned_documents) > 10:
            print("  ... and %d more documents" % (len(unowned_documents) - 10))

        if args.dry_run:
            print("dry run: nothing written")
            return 0

        if not unowned_projects and not unowned_documents:
            print("nothing to claim")
            return 0

        for project in unowned_projects:
            project.user_id = user.id
        for document in unowned_documents:
            document.user_id = user.id
        db.commit()

        print("claimed %d project(s) and %d document(s) for %s" % (
            len(unowned_projects), len(unowned_documents), user.username))
        remaining_projects = db.query(func.count(Project.id)).filter(
            Project.user_id.is_(None)).scalar() or 0
        remaining_documents = db.query(func.count(Document.id)).filter(
            Document.user_id.is_(None)).scalar() or 0
        print("still ownerless: %d project(s), %d document(s)" % (
            remaining_projects, remaining_documents))
        return 0
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
