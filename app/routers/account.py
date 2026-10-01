"""Self-service account actions (any signed-in user)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..database import get_db
from ..dependencies import require_api_user
from ..models import User

router = APIRouter(prefix="/api/account", tags=["account"])


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1)


@router.post("/password")
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(require_api_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}
