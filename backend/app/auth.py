"""
Password hashing + JWT issuing/verification, and the FastAPI dependencies that
enforce role-based access (NFR-1: authorization is enforced server-side here,
not left to the frontend to "just not show the button").
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .database import get_db

# NOTE: in production this MUST come from a real secret manager / env var.
_env = os.environ.get("MEDIPASS_ENV", "").lower()
_secret = os.environ.get("MEDIPASS_SECRET_KEY")
if not _secret:
    if _env == "development":
        _secret = "dev-only-secret-change-me"
    else:
        raise RuntimeError(
            "MEDIPASS_SECRET_KEY is not set and MEDIPASS_ENV is not 'development'. "
            "Set MEDIPASS_SECRET_KEY in your .env or export it as an environment variable."
        )
SECRET_KEY = _secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


def require_role(role: models.UserRole):
    """Dependency factory: use as Depends(require_role(UserRole.patient))."""

    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires role '{role.value}'.",
            )
        return user

    return checker
