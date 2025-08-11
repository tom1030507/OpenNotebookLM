"""
Authentication service for user management and JWT tokens.
"""

import jwt
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, DateTime, Boolean, Integer
import secrets
import os
from pathlib import Path

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Database setup
Base = declarative_base()
DATABASE_URL = "sqlite:///data/auth.db"

class User(Base):
    """User model for authentication."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

class AuthService:
    """Service for authentication and user management."""
    
    def __init__(self):
        """Initialize authentication service."""
        # Ensure data directory exists
        Path("data").mkdir(exist_ok=True)
        
        # Create database engine
        self.engine = create_engine(DATABASE_URL)
        Base.metadata.create_all(bind=self.engine)
    
    def _get_db(self) -> Session:
        """Get database session."""
        from sqlalchemy.orm import sessionmaker
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        return SessionLocal()
    
    def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.
        
        Args:
            password: Plain text password
            
        Returns:
            Hashed password
        """
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.
        
        Args:
            plain_password: Plain text password
            hashed_password: Hashed password
            
        Returns:
            True if password matches
        """
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        is_admin: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new user.
        
        Args:
            username: Username
            email: Email address
            password: Plain text password
            is_admin: Whether user is admin
            
        Returns:
            User data if successful, None otherwise
        """
        db = self._get_db()
        try:
            # Check if user already exists
            existing_user = db.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()
            
            if existing_user:
                return None
            
            # Create new user
            hashed_password = self.hash_password(password)
            user = User(
                username=username,
                email=email,
                hashed_password=hashed_password,
                is_admin=is_admin
            )
            
            db.add(user)
            db.commit()
            db.refresh(user)
            
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_admin": user.is_admin,
                "created_at": user.created_at.isoformat()
            }
        finally:
            db.close()
    
    def authenticate_user(
        self,
        username: str,
        password: str
    ) -> Optional[Dict[str, Any]]:
        """
        Authenticate a user.
        
        Args:
            username: Username or email
            password: Plain text password
            
        Returns:
            User data if authentication successful
        """
        db = self._get_db()
        try:
            # Find user by username or email
            user = db.query(User).filter(
                (User.username == username) | (User.email == username)
            ).first()
            
            if not user:
                return None
            
            if not self.verify_password(password, user.hashed_password):
                return None
            
            if not user.is_active:
                return None
            
            # Update last login
            user.last_login = datetime.utcnow()
            db.commit()
            
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_admin": user.is_admin,
                "is_active": user.is_active
            }
        finally:
            db.close()
    
    def create_access_token(
        self,
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create a JWT access token.
        
        Args:
            data: Token payload data
            expires_delta: Token expiration time
            
        Returns:
            JWT token string
        """
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def create_refresh_token(self, data: Dict[str, Any]) -> str:
        """
        Create a JWT refresh token.
        
        Args:
            data: Token payload data
            
        Returns:
            JWT refresh token string
        """
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify and decode a JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Token payload if valid, None otherwise
        """
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.JWTError:
            return None
    
    def get_current_user(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Get current user from JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            User data if token valid
        """
        payload = self.verify_token(token)
        if not payload:
            return None
        
        username = payload.get("sub")
        if not username:
            return None
        
        db = self._get_db()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user or not user.is_active:
                return None
            
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_admin": user.is_admin,
                "is_active": user.is_active
            }
        finally:
            db.close()
    
    def update_password(
        self,
        username: str,
        old_password: str,
        new_password: str
    ) -> bool:
        """
        Update user password.
        
        Args:
            username: Username
            old_password: Current password
            new_password: New password
            
        Returns:
            True if successful
        """
        db = self._get_db()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return False
            
            if not self.verify_password(old_password, user.hashed_password):
                return False
            
            user.hashed_password = self.hash_password(new_password)
            db.commit()
            return True
        finally:
            db.close()
    
    def delete_user(self, username: str) -> bool:
        """
        Delete a user (soft delete by deactivating).
        
        Args:
            username: Username
            
        Returns:
            True if successful
        """
        db = self._get_db()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return False
            
            user.is_active = False
            db.commit()
            return True
        finally:
            db.close()
    
    def list_users(self, skip: int = 0, limit: int = 100) -> list:
        """
        List all users.
        
        Args:
            skip: Number of users to skip
            limit: Maximum number of users to return
            
        Returns:
            List of user data
        """
        db = self._get_db()
        try:
            users = db.query(User).offset(skip).limit(limit).all()
            return [
                {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "is_admin": user.is_admin,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat(),
                    "last_login": user.last_login.isoformat() if user.last_login else None
                }
                for user in users
            ]
        finally:
            db.close()
    
    def create_default_admin(self):
        """Create a default admin user if none exists."""
        db = self._get_db()
        try:
            # Check if any admin exists
            admin = db.query(User).filter(User.is_admin == True).first()
            if not admin:
                # Create default admin
                self.create_user(
                    username="admin",
                    email="admin@opennotebooklm.local",
                    password="admin123",  # Change this in production!
                    is_admin=True
                )
                print("Default admin user created (username: admin, password: admin123)")
                print("IMPORTANT: Change the default password immediately!")
        finally:
            db.close()

# Singleton instance
auth_service = AuthService()

# Create default admin on startup
auth_service.create_default_admin()
