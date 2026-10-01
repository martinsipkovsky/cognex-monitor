"""User management API (admin / manage_users permission)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..database import get_db
from ..dependencies import require_permission
from ..models import PERMISSIONS, User
from ..schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_permission("manage_users"))):
    return db.query(User).order_by(User.id).all()


@router.get("/permissions")
def list_permissions(_: User = Depends(require_permission("manage_users"))):
    return PERMISSIONS


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_users")),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(409, "Username already exists")
    bad = set(payload.permissions) - set(PERMISSIONS)
    if bad:
        raise HTTPException(400, f"Unknown permissions: {sorted(bad)}")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
        permissions=payload.permissions,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("manage_users")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_active is not None:
        if user.id == actor.id and payload.is_active is False:
            raise HTTPException(400, "You cannot deactivate your own account")
        user.is_active = payload.is_active
    if payload.permissions is not None:
        bad = set(payload.permissions) - set(PERMISSIONS)
        if bad:
            raise HTTPException(400, f"Unknown permissions: {sorted(bad)}")
        user.permissions = payload.permissions
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("manage_users")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == actor.id:
        raise HTTPException(400, "You cannot delete your own account")
    if user.is_admin and db.query(User).filter(User.is_admin.is_(True)).count() <= 1:
        raise HTTPException(400, "Cannot delete the last admin account")
    db.delete(user)
    db.commit()
