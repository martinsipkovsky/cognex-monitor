"""FastAPI dependencies for auth and permission gating."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .auth import SESSION_COOKIE, read_session_token
from .database import get_db
from .models import User


class RedirectToLogin(Exception):
    """Raised by page dependencies so the app can send a browser to /login."""


def current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = read_session_token(token)
    if uid is None:
        return None
    user = db.get(User, uid)
    if user and user.is_active:
        return user
    return None


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """For HTML pages: redirect to /login when not signed in."""
    user = current_user(request, db)
    if user is None:
        raise RedirectToLogin()
    return user


def require_api_user(request: Request, db: Session = Depends(get_db)) -> User:
    """For JSON APIs: 401 when not signed in."""
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_permission(key: str):
    """Dependency factory that enforces a granular permission for APIs."""

    def _dep(user: User = Depends(require_api_user)) -> User:
        if not user.has_permission(key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {key}",
            )
        return user

    return _dep


def require_page_permission(key: str):
    """Same as require_permission but for HTML pages (redirects/403 page)."""

    def _dep(user: User = Depends(require_user)) -> User:
        if not user.has_permission(key):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {key}")
        return user

    return _dep
