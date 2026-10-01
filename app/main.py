"""FastAPI application entrypoint.

Creates the schema on startup, seeds the default admin, starts the background
poller and the TCP listener for cameras that push data, and wires up the API
routers, HTML pages and static assets.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import settings
from .database import Base, SessionLocal, engine, migrate_schema
from .dependencies import RedirectToLogin
from .poller import listener, poller
from .routers import account, auth_routes, data, database_admin, devices, notifications, pages, users
from .seed import seed_admin
from .templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The app owns its schema fully.
    Base.metadata.create_all(bind=engine)
    migrate_schema(engine)
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
    if settings.poll_enabled:
        poller.start()
        listener.start()
    yield
    listener.stop()
    poller.stop()


app = FastAPI(title="Cognex Monitor", lifespan=lifespan)

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.exception_handler(RedirectToLogin)
async def _redirect_to_login(request: Request, exc: RedirectToLogin):
    return RedirectResponse(url="/login", status_code=303)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# JSON API
app.include_router(auth_routes.router)
app.include_router(account.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(data.router)
app.include_router(notifications.router)
app.include_router(database_admin.router)
# HTML pages (registered last so /api/* wins)
app.include_router(pages.router)
