"""Startup demo-account seeding tests."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User
from app.services.auth import AuthService
from app.services.bootstrap import ensure_demo_account


def database_factory():
    """Create an isolated account database and session factory.

    Returns:
        SQLAlchemy session factory backed by one in-memory database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_seeds_the_demo_account_and_reports_advertisable_credentials():
    """A database without the demo account gains one that can be advertised."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    with sessions() as db:
        advertisement = ensure_demo_account(
            db,
            service,
            enabled=True,
            username="demo",
            email="demo@example.com",
            password="demo1234",
        )

        stored = db.query(User).filter(User.username == "demo").one()
        assert stored.email == "demo@example.com"
        assert service.verify_password("demo1234", stored.hashed_password)
        assert advertisement is not None
        assert advertisement.username == "demo"
        assert advertisement.password == "demo1234"


def test_disabled_seeding_creates_nothing_and_advertises_nothing():
    """A deployment that opted out gets no account and no hint."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    with sessions() as db:
        advertisement = ensure_demo_account(
            db,
            service,
            enabled=False,
            username="demo",
            email="demo@example.com",
            password="demo1234",
        )

        assert advertisement is None
        assert db.query(User).count() == 0


def test_password_changed_by_hand_is_kept_and_stops_being_advertised():
    """Seeding never overwrites a password somebody deliberately changed."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    with sessions() as db:
        service.register_user(db, "demo", "demo@example.com", "chosen-by-a-human")
        original_hash = db.query(User).filter(User.username == "demo").one().hashed_password

        advertisement = ensure_demo_account(
            db,
            service,
            enabled=True,
            username="demo",
            email="demo@example.com",
            password="demo1234",
        )

        stored = db.query(User).filter(User.username == "demo").one()
        assert stored.hashed_password == original_hash
        assert service.verify_password("chosen-by-a-human", stored.hashed_password)
        # Advertising `demo1234` here would print a password that cannot sign in.
        assert advertisement is None
        assert db.query(User).count() == 1


def test_demo_account_is_seeded_even_once_real_accounts_exist():
    """The demo account is not a first-run bootstrap; it is always present."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    with sessions() as db:
        service.register_user(db, "a-real-person", "person@example.com", "their-password")

        advertisement = ensure_demo_account(
            db,
            service,
            enabled=True,
            username="demo",
            email="demo@example.com",
            password="demo1234",
        )

        assert advertisement is not None
        assert db.query(User).filter(User.username == "demo").count() == 1
        assert db.query(User).count() == 2


def test_seeding_an_already_seeded_database_adds_no_second_account():
    """Restarting keeps advertising the same single demo account."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    seed = dict(
        enabled=True,
        username="demo",
        email="demo@example.com",
        password="demo1234",
    )
    with sessions() as db:
        first = ensure_demo_account(db, service, **seed)
        second = ensure_demo_account(db, service, **seed)

        assert first == second
        assert db.query(User).count() == 1


def test_a_password_the_api_would_reject_is_skipped_rather_than_stored():
    """A misconfigured password leaves no account and does not stop startup."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    with sessions() as db:
        advertisement = ensure_demo_account(
            db,
            service,
            enabled=True,
            username="demo",
            email="demo@example.com",
            # Under the eight-character floor `UserRegister` enforces, so
            # registering through the API could never produce this account.
            password="short",
        )

        assert advertisement is None
        assert db.query(User).count() == 0
