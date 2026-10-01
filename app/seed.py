"""First-run seeding: create the default admin account if no users exist."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .auth import hash_password
from .config import settings
from .models import User


def seed_admin(db: Session) -> None:
    if db.query(User).count() > 0:
        return
    admin = User(
        username=settings.default_admin_user,
        password_hash=hash_password(settings.default_admin_password),
        is_admin=True,
        is_active=True,
        permissions=[],
    )
    db.add(admin)
    db.commit()
