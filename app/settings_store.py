"""Second copy of the app's file settings, kept in the environment database.

The database chosen on the Database page and the FTP backup settings are
files in DATA_DIR. That folder only survives an image update when docker
keeps it in a volume; a server whose docker-compose.yml has no volume for it
(older versions of the file had none) loses the files every time the
container is recreated. So every save is also written to a small table in
the database from DATABASE_URL (the Postgres container next to the app,
whose data is always in a volume), and a file that is missing at startup is
put back from there.

The table is deliberately not part of the app's models: backups and restores
leave it alone, and it stays in the environment database even when the app
uses another database chosen on the Database page.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.engine import Engine

from .config import settings

log = logging.getLogger("cognex.settings")

_metadata = MetaData()
app_settings = Table(
    "app_settings",
    _metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)

_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        url = settings.database_url
        args = {"connect_timeout": 5} if url.startswith("postgresql") else {}
        if url.startswith("sqlite"):
            args = {"check_same_thread": False}
        _engine = create_engine(url, pool_pre_ping=True, connect_args=args)
    return _engine


def save(key: str, value: Any) -> bool:
    """Store a copy; None deletes it. Never raises (the file is the original)."""
    try:
        eng = engine()
        _metadata.create_all(eng)
        with eng.begin() as conn:
            conn.execute(app_settings.delete().where(app_settings.c.key == key))
            if value is not None:
                conn.execute(app_settings.insert().values(
                    key=key, value=json.dumps(value), updated_at=dt.datetime.now(dt.timezone.utc)))
        return True
    except Exception as exc:  # noqa: BLE001 - a missing copy must not break saving
        log.warning("could not keep a copy of setting %s in the database: %s", key, exc)
        return False


def load(key: str) -> Any:
    try:
        eng = engine()
        _metadata.create_all(eng)
        with eng.connect() as conn:
            raw = conn.execute(select(app_settings.c.value).where(app_settings.c.key == key)).scalar()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read setting %s from the database: %s", key, exc)
        return None
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None
