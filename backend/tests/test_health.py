"""HTTP tests for the process liveness and database readiness contracts."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.database import get_db
from app.routers.health import router
from app.services.auth import get_auth_service


class HealthySession:
    """Database double that accepts a readiness query."""

    def execute(self, _query):
        """Accept a query without contacting an external database.

        Args:
            _query: SQLAlchemy query issued by the readiness route.

        Returns:
            None because the route only needs the query to succeed.
        """
        return None


class FailingSession:
    """Database double that rejects a readiness query."""

    def execute(self, _query):
        """Raise the private database error the response must conceal.

        Args:
            _query: SQLAlchemy query issued by the readiness route.

        Returns:
            This method never returns.

        Raises:
            RuntimeError: Always, to simulate an unavailable database.
        """
        raise RuntimeError('private database credentials were rejected')


def _client_with_db(session) -> TestClient:
    """Create a health-only app whose database dependency yields a session.

    Args:
        session: Session double supplied to the health router.

    Returns:
        Test client for the isolated health application.
    """
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def test_readyz_returns_200_when_database_accepts_queries():
    """A reachable database makes the instance ready for traffic."""
    response = _client_with_db(HealthySession()).get('/readyz')

    assert response.status_code == 200
    assert response.json() == {'ok': True}


def test_readyz_returns_503_without_leaking_database_errors():
    """A broken database removes the instance without exposing credentials."""
    response = _client_with_db(FailingSession()).get('/readyz')

    assert response.status_code == 503
    assert response.json() == {'ok': False}
    assert 'credentials' not in response.text


@pytest.mark.parametrize('jwt_secret', [None, '   '], ids=['missing', 'blank'])
def test_production_lifespan_refuses_an_unusable_jwt_secret(
    monkeypatch,
    jwt_secret,
):
    """Production must fail at startup, before the first authenticated call."""
    from app.lifecycle import lifespan

    monkeypatch.setenv('APP_ENV', 'production')
    if jwt_secret is None:
        monkeypatch.delenv('JWT_SECRET_KEY', raising=False)
    else:
        monkeypatch.setenv('JWT_SECRET_KEY', jwt_secret)

    get_settings.cache_clear()
    get_auth_service.cache_clear()
    startup_app = FastAPI(lifespan=lifespan)
    try:
        with pytest.raises(RuntimeError, match='JWT_SECRET_KEY'):
            with TestClient(startup_app):
                pass
    finally:
        get_auth_service.cache_clear()
        get_settings.cache_clear()
