"""Authentication router: register, sign in and identify the caller."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.db.models import User
from app.schemas import TokenResponse, UserRegister, UserResponse
from app.services.auth import AuthService, DuplicateUserError, get_auth_service

router = APIRouter()
logger = structlog.get_logger()

# auto_error=False so a missing header reaches get_current_user and produces the
# same 401 as a bad one.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

INVALID_CREDENTIALS = "Incorrect username or password"
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """Resolve the bearer token to the signed-in account."""
    user = token and auth_service.get_user_from_token(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers=BEARER_CHALLENGE,
        )
    return user


@router.post("/auth/register", response_model=UserResponse)
async def register(
    user_data: UserRegister,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Register a new account."""
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


@router.post("/auth/token", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Exchange username and password for an access token."""
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
