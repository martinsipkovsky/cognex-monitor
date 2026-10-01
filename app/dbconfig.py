"""Database connection chosen on the Database page.

The setting cannot live inside the database it points to, so it is kept in a
small JSON file in DATA_DIR (a docker volume, see docker-compose). It is read
once at startup by app.database; saving a new one takes effect on restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from .config import settings

FIELDS = ("host", "port", "database", "user", "password")


def _path() -> Path:
    return Path(settings.data_dir) / "database.json"


def load() -> dict | None:
    path = _path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("host") else None


def save(cfg: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: cfg.get(k) for k in FIELDS}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def clear() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass


def build_url(cfg: dict) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=cfg.get("user") or None,
        password=cfg.get("password") or None,
        host=cfg.get("host") or None,
        port=int(cfg["port"]) if cfg.get("port") else None,
        database=cfg.get("database") or None,
    ).render_as_string(hide_password=False)


def describe_url(url: str) -> dict:
    """Connection details of a URL without the password."""
    u = make_url(url)
    return {
        "driver": u.drivername,
        "host": u.host,
        "port": u.port,
        "database": u.database,
        "user": u.username,
    }


def test_url(url: str, timeout: int = 5) -> tuple[bool, str | None]:
    """Try to connect and run SELECT 1. Returns (ok, error message)."""
    connect_args = {"connect_timeout": timeout} if url.startswith("postgresql") else {}
    try:
        eng = create_engine(url, connect_args=connect_args, pool_pre_ping=False)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            eng.dispose()
    except Exception as exc:  # noqa: BLE001 - report any driver error to the UI
        msg = str(getattr(exc, "orig", None) or exc).strip().splitlines()
        return False, (msg[0] if msg else exc.__class__.__name__)
    return True, None
