"""
Authentication API endpoints for user management and login.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

from app.services.auth import auth_service

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# Request/Response models
class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool
    created_at: str
    last_login: Optional[str] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

# Dependency to get current user
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get current user from JWT token."""
    user = auth_service.get_current_user(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# Dependency to require admin user
async def require_admin(current_user: dict = Depends(get_current_user)):
    """Require admin privileges."""
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserRegister):
    """
    Register a new user.
    
    Args:
        user_data: User registration data
        
    Returns:
        Created user data
    """
    user = auth_service.create_user(
        username=user_data.username,
        email=user_data.email,
        password=user_data.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists"
        )
    
    return UserResponse(**user)

@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Login with username/password to get access token.
    
    Args:
        form_data: OAuth2 password form
        
    Returns:
        Access and refresh tokens
    """
    user = auth_service.authenticate_user(
        username=form_data.username,
        password=form_data.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create tokens
    access_token = auth_service.create_access_token(
        data={"sub": user["username"]}
    )
    refresh_token = auth_service.create_refresh_token(
        data={"sub": user["username"]}
    )
    
    return Token(
        access_token=access_token,
        refresh_token=refresh_token
    )

@router.post("/refresh", response_model=Token)
async def refresh_token(refresh_token: str):
    """
    Refresh access token using refresh token.
    
    Args:
        refresh_token: JWT refresh token
        
    Returns:
        New access and refresh tokens
    """
    payload = auth_service.verify_token(refresh_token)
    
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Create new tokens
    access_token = auth_service.create_access_token(
        data={"sub": username}
    )
    new_refresh_token = auth_service.create_refresh_token(
        data={"sub": username}
    )
    
    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token
    )

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Get current user information.
    
    Returns:
        Current user data
    """
    return UserResponse(**current_user)

@router.put("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: dict = Depends(get_current_user)
):
    """
    Change current user's password.
    
    Args:
        password_data: Old and new passwords
        
    Returns:
        Success message
    """
    success = auth_service.update_password(
        username=current_user["username"],
        old_password=password_data.old_password,
        new_password=password_data.new_password
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update password. Check your current password."
        )
    
    return {"message": "Password updated successfully"}

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(require_admin)
):
    """
    List all users (admin only).
    
    Args:
        skip: Number of users to skip
        limit: Maximum number of users to return
        
    Returns:
        List of users
    """
    users = auth_service.list_users(skip=skip, limit=limit)
    return [UserResponse(**user) for user in users]

@router.delete("/users/{username}")
async def delete_user(
    username: str,
    current_user: dict = Depends(require_admin)
):
    """
    Delete (deactivate) a user (admin only).
    
    Args:
        username: Username to delete
        
    Returns:
        Success message
    """
    if username == current_user["username"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    success = auth_service.delete_user(username)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {"message": f"User {username} deactivated successfully"}

@router.post("/users/{username}/admin")
async def make_admin(
    username: str,
    current_user: dict = Depends(require_admin)
):
    """
    Grant admin privileges to a user (admin only).
    
    Args:
        username: Username to make admin
        
    Returns:
        Success message
    """
    # This would require adding a method to auth_service
    # For now, return not implemented
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Admin promotion not yet implemented"
    )

@router.get("/validate")
async def validate_token(current_user: dict = Depends(get_current_user)):
    """
    Validate current token.
    
    Returns:
        Validation status
    """
    return {
        "valid": True,
        "username": current_user["username"],
        "is_admin": current_user["is_admin"]
    }
