"""Password hashing and session-cookie helpers."""
from __future__ import annotations

from typing import Optional

from itsdangerous import BadSignature, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .models import User

# pbkdf2_sha256 is pure-Python (via passlib) so the app has no dependency on a
# native bcrypt build. Existing bcrypt hashes are still verified if present.
_pwd = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")

SESSION_COOKIE = "cognex_session"
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="cognex-session")


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _pwd.verify(raw, hashed)
    except ValueError:
        return False


def make_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str, max_age: int = 60 * 60 * 12) -> Optional[int]:
    """Return the user id in a valid token, or None."""
    try:
        data = _serializer.loads(token, max_age=max_age)
    except BadSignature:
        return None
    return data.get("uid")


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
