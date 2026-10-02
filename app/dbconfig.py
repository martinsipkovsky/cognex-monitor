"""Database connection chosen on the Database page.

The setting cannot live inside the database it points to, so it is kept in a
small JSON file in DATA_DIR (a docker volume, see docker-compose), with a copy
in the environment database (app.settings_store) that puts the file back if
an image update lost it. It is read once at startup by app.database; saving a
new one takes effect on restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from . import settings_store
from .config import settings

FIELDS = ("host", "port", "database", "user", "password")


def _path() -> Path:
    return Path(settings.data_dir) / "database.json"


KEY = "database"


def load() -> dict | None:
    path = _path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("host") else None


def _write(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save(cfg: dict) -> None:
    data = {k: cfg.get(k) for k in FIELDS}
    _write(data)
    settings_store.save(KEY, data)


def clear() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
    settings_store.save(KEY, None)


def restore_missing() -> bool:
    """Put the file back from the database copy if it is gone (see module doc).

    When the file is there, make sure the copy matches it (installs from before
    the copy existed get one on their first start).
    """
    if _path().exists():
        data = load()
        if data and settings_store.load(KEY) != data:
            settings_store.save(KEY, data)
        return False
    data = settings_store.load(KEY)
    if not isinstance(data, dict) or not data.get("host"):
        return False
    _write({k: data.get(k) for k in FIELDS})
    return True


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
