"""Authentication router: register, sign in and identify the caller."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.config import Settings, get_settings
from app.db.models import User
from app.schemas import (
    DemoAccountResponse,
    PersonalAPIKeyCreate,
    PersonalAPIKeyCreatedResponse,
    PersonalAPIKeyResponse,
    TokenResponse,
    UserRegister,
    UserResponse,
)
from app.services.api_keys import (
    create_personal_api_key,
    get_user_from_api_key,
    list_personal_api_keys,
    revoke_personal_api_key,
)
from app.services.auth import AuthService, DuplicateUserError, get_auth_service
from app.services.bootstrap import advertised_demo_account
from app.routers.rate_limit import limit_login, limit_registration

router = APIRouter()
logger = structlog.get_logger()

# auto_error=False so a missing header reaches get_current_user and produces the
# same 401 as a bad one.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

INVALID_CREDENTIALS = "Incorrect username or password"
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def _credentials_error() -> HTTPException:
    """Return the shared response for missing, invalid, or revoked tokens."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers=BEARER_CHALLENGE,
    )


def require_public_registration(
    settings: Settings = Depends(get_settings),
) -> None:
    """Refuse public enrollment when the deployment has not enabled it.

    Args:
        settings: Application enrollment policy.

    Returns:
        None when public registration is enabled.

    Raises:
        HTTPException: With status 403 when enrollment is closed.
    """
    if not settings.allow_public_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled",
        )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """Resolve the bearer token to the signed-in account.

    Args:
        token: Presented bearer token, if any.
        db: Database session.
        auth_service: Token validation service.

    Returns:
        Active account identified by the token.
    """
    user = token and auth_service.get_user_from_token(db, token)
    if not user and token:
        user = get_user_from_api_key(db, token)
    if not user:
        raise _credentials_error()
    return user


async def get_current_user_jwt(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """Resolve a signed-in account for API-key management routes.

    Args:
        token: Presented bearer token, if any.
        db: Database session.
        auth_service: Token validation service.

    Returns:
        Active account identified by a JWT.

    Raises:
        HTTPException: With status 401 when the bearer token is not a valid JWT.
    """
    user = token and auth_service.get_user_from_token(db, token)
    if not user:
        raise _credentials_error()
    return user


@router.post(
    "/auth/register",
    response_model=UserResponse,
    dependencies=[Depends(require_public_registration), Depends(limit_registration)],
)
async def register(
    user_data: UserRegister,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Register a new account when public enrollment is enabled.

    Args:
        user_data: Validated username, email, and password.
        db: Database session.
        auth_service: Account/password service.

    Returns:
        Created account without password material.
    """
    try:
        return auth_service.register_user(
            db,
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
        )
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    dependencies=[Depends(limit_login)],
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Exchange username and password for an access token.

    Args:
        form_data: OAuth2 username/password form.
        db: Database session.
        auth_service: Account/password/token service.

    Returns:
        Signed bearer token response.
    """
    user = auth_service.authenticate_user(
        db,
        username=form_data.username,
        password=form_data.password,
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS,
            headers=BEARER_CHALLENGE,
        )

    return TokenResponse(access_token=auth_service.create_access_token(user.username))


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the account the presented token belongs to."""
    return current_user


@router.post(
    "/auth/api-keys",
    response_model=PersonalAPIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: PersonalAPIKeyCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_jwt),
):
    """Create a named personal key and return the secret once.

    Args:
        request: Validated name for the new key.
        db: Database session.
        current_user: Account authenticated by a JWT.

    Returns:
        Key metadata and the newly generated bearer secret.
    """
    response.headers["Cache-Control"] = "no-store"
    record, secret = create_personal_api_key(db, current_user, request.name)
    return PersonalAPIKeyCreatedResponse(
        id=record.id,
        name=record.name,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        api_key=secret,
    )


@router.get(
    "/auth/api-keys",
    response_model=list[PersonalAPIKeyResponse],
)
async def get_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_jwt),
):
    """List the caller's key metadata without returning any secret.

    Args:
        db: Database session.
        current_user: Account authenticated by a JWT.

    Returns:
        The caller's personal API keys in newest-first order.
    """
    return list_personal_api_keys(db, current_user)


@router.delete("/auth/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_jwt),
):
    """Revoke one of the caller's personal API keys.

    Args:
        key_id: Key row id to revoke.
        db: Database session.
        current_user: Account authenticated by a JWT.

    Returns:
        An empty 204 response when the key was deleted.

    Raises:
        HTTPException: With status 404 when the key is missing or belongs to
            another account.
    """
    if not revoke_personal_api_key(db, current_user, key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/auth/demo-account",
    response_model=DemoAccountResponse,
    dependencies=[Depends(limit_login)],
)
async def get_demo_account(
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
):
    """Tell the sign-in page which demo credentials it may offer.

    Args:
        db: Database session.
        auth_service: Password hashing/account service.
        settings: Demo-account policy for this deployment.

    Returns:
        The advertisable credentials, or a disabled response when there are
        none. The stored password is verified, so this never advertises one
        that would fail to sign in.
    """
    account = advertised_demo_account(
        db,
        auth_service,
        enabled=settings.seed_demo_user,
        username=settings.demo_username,
        email=settings.demo_email,
        password=settings.demo_password,
    )
    if account is None:
        return DemoAccountResponse(enabled=False)
    return DemoAccountResponse(
        enabled=True,
        username=account.username,
        password=account.password,
    )
