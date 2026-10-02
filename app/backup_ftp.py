"""Automatic backups uploaded to an FTP / FTPS server.

The settings live in DATA_DIR/backup_ftp.json (like the database setting, so
they survive restores and database switches), with a copy in the environment
database (app.settings_store) that puts the file back if an image update lost
it. A daemon thread checks every
30 seconds whether a run is due: daily at a set time in the admin's time
zone, or every N hours. Each run writes a backup file, uploads it to the
remote folder and deletes the oldest backups there beyond ``keep``.
"""
from __future__ import annotations

import datetime as dt
import ftplib
import io
import json
import logging
import os
import posixpath
import shutil
import ssl
import threading
from pathlib import Path

from . import backup, settings_store
from .scrap_stats import zone

log = logging.getLogger("cognex.backup")

FIELDS = (
    "enabled", "host", "port", "user", "password", "folder", "tls",
    "schedule", "daily_time", "interval_hours", "keep", "timezone", "saved_at",
)
DEFAULTS = {
    "enabled": False, "host": "", "port": 21, "user": "", "password": "", "folder": "/",
    "tls": False, "schedule": "daily", "daily_time": "02:00", "interval_hours": 24,
    "keep": 14, "timezone": "UTC", "saved_at": None,
}
TIMEOUT = 30


def _path() -> Path:
    return backup.data_dir() / "backup_ftp.json"


KEY = "backup_ftp"


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in (data if isinstance(data, dict) else {}).items() if k in FIELDS}}


def _write(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save(cfg: dict) -> dict:
    data = {**DEFAULTS, **{k: cfg.get(k, DEFAULTS[k]) for k in FIELDS}}
    _write(data)
    settings_store.save(KEY, data)
    return data


def restore_missing() -> bool:
    """Put the file back from the database copy if it is gone (see module doc).

    When the file is there, make sure the copy matches it.
    """
    if _path().exists():
        data = load()
        if settings_store.load(KEY) != data:
            settings_store.save(KEY, data)
        return False
    data = settings_store.load(KEY)
    if not isinstance(data, dict):
        return False
    _write({**DEFAULTS, **{k: v for k, v in data.items() if k in FIELDS}})
    log.warning("FTP backup settings were missing from DATA_DIR; restored them from the database copy")
    return True


# --------------------------------------------------------------------------- #
# FTP
# --------------------------------------------------------------------------- #


class _FTP_TLS(ftplib.FTP_TLS):
    """Explicit TLS that reuses the control connection's TLS session on data
    connections; many servers (vsftpd, FileZilla Server) require that."""

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def connect(cfg: dict) -> ftplib.FTP:
    """Log in and change to the remote folder, creating it if needed."""
    if cfg.get("tls"):
        # the certificate is not verified: NAS boxes mostly use self-signed ones
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ftp: ftplib.FTP = _FTP_TLS(context=ctx, timeout=TIMEOUT)
    else:
        ftp = ftplib.FTP(timeout=TIMEOUT)
    try:
        ftp.connect(cfg["host"], int(cfg.get("port") or 21))
        ftp.login(cfg.get("user") or "anonymous", cfg.get("password") or "")
        if cfg.get("tls"):
            ftp.prot_p()
        folder = (cfg.get("folder") or "").strip()
        if folder.startswith("/"):
            ftp.cwd("/")
        for part in [p for p in folder.split("/") if p]:
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                ftp.mkd(part)
                ftp.cwd(part)
    except BaseException:
        _quit(ftp)
        raise
    return ftp


def _quit(ftp: ftplib.FTP) -> None:
    try:
        ftp.quit()
    except Exception:  # noqa: BLE001
        ftp.close()


def _error(exc: Exception) -> str:
    if isinstance(exc, ftplib.error_perm):
        return f"The server refused: {exc}"
    if isinstance(exc, ssl.SSLError):
        return f"TLS failed: {exc}. Check that the server supports explicit FTPS (AUTH TLS) on this port."
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return f"Cannot reach the server: {exc}"
    return str(exc) or exc.__class__.__name__


def test(cfg: dict) -> tuple[bool, str]:
    """Log in, open the folder and write and delete a small file."""
    try:
        ftp = connect(cfg)
    except Exception as exc:  # noqa: BLE001
        return False, _error(exc)
    try:
        name = ".cognex-monitor-test"
        ftp.storbinary(f"STOR {name}", io.BytesIO(b"test"))
        ftp.delete(name)
        where = ftp.pwd()
        files = _backup_names(ftp)
    except Exception as exc:  # noqa: BLE001
        return False, "Logged in, but cannot write to the folder: " + _error(exc)
    finally:
        _quit(ftp)
    return True, f"Connection works. Folder {where} is writable and holds {len(files)} backup(s)."


def _backup_names(ftp: ftplib.FTP) -> list[str]:
    try:
        names = ftp.nlst()
    except ftplib.error_perm:  # some servers answer 550 for an empty folder
        names = []
    return sorted({posixpath.basename(n) for n in names if backup.NAME_RE.match(posixpath.basename(n))})


def upload(cfg: dict, path: Path) -> list[str]:
    """Upload ``path`` and delete old backups beyond keep. Returns deleted names."""
    ftp = connect(cfg)
    try:
        part = path.name + ".part"
        with path.open("rb") as f:
            ftp.storbinary(f"STOR {part}", f)
        ftp.rename(part, path.name)  # a cut-off upload never looks like a backup
        keep = max(1, int(cfg.get("keep") or 1))
        old = _backup_names(ftp)[:-keep]
        for name in old:
            ftp.delete(name)
        return old
    finally:
        _quit(ftp)


def run(cfg: dict | None = None, trigger: str = "schedule") -> dict:
    """One backup to FTP. Records the result and returns it."""
    cfg = cfg or load()
    started = backup.utcnow()
    result = {"at": started.isoformat(), "trigger": trigger, "ok": False}
    tmpdir = None
    try:
        if not cfg.get("host"):
            raise ValueError("No FTP server is set.")
        with backup.lock:
            path = backup.make_backup()
            tmpdir = path.parent
            size = path.stat().st_size
            deleted = upload(cfg, path)
        result.update(ok=True, file=path.name, size=size, deleted=len(deleted),
                      seconds=round((backup.utcnow() - started).total_seconds(), 1))
        result["message"] = f"Uploaded {path.name}" + (f", removed {len(deleted)} old backup(s)" if deleted else "")
        backup.record_backup("ftp", path.name, size)
    except Exception as exc:  # noqa: BLE001 - report every failure on the page
        log.warning("FTP backup failed: %s", exc)
        result["message"] = _error(exc) if not isinstance(exc, ValueError) else str(exc)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    backup.update_state(ftp_last_run=result)
    from . import notifications  # local import: notifications imports the models

    how = "scheduled" if trigger == "schedule" else "manual"
    if result["ok"]:
        notifications.emit_system("backup_ok", f"FTP backup ({how}) finished: {result['message']}")
    else:
        notifications.emit_system("backup_failed", f"FTP backup ({how}) failed: {result['message']}")
    return result


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #


def _parse(iso: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def next_run(cfg: dict, last_attempt: dt.datetime | None, now: dt.datetime) -> dt.datetime | None:
    """When the next automatic run is due (UTC), or None when switched off."""
    if not cfg.get("enabled") or not cfg.get("host"):
        return None
    since = max(filter(None, [last_attempt, _parse(cfg.get("saved_at"))]), default=now)
    if cfg.get("schedule") == "interval":
        hours = max(1, int(cfg.get("interval_hours") or 24))
        return last_attempt + dt.timedelta(hours=hours) if last_attempt else since
    tz = zone(cfg.get("timezone"))
    try:
        hh, mm = (int(x) for x in str(cfg.get("daily_time") or "02:00").split(":")[:2])
        at = dt.time(hh, mm)
    except ValueError:
        at = dt.time(2, 0)
    local = since.astimezone(tz)
    candidate = dt.datetime.combine(local.date(), at, tz)
    if candidate <= local:
        candidate = dt.datetime.combine(local.date() + dt.timedelta(days=1), at, tz)
    return candidate.astimezone(dt.timezone.utc)


def last_attempt() -> dt.datetime | None:
    """Start of the last scheduled run ("Run now" does not move the schedule)."""
    return _parse(backup.load_state().get("ftp_last_scheduled_at"))


class Scheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        restore_missing()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cognex-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(30):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - never let the loop die
                log.exception("backup scheduler failed")

    def tick(self, now: dt.datetime | None = None) -> dict | None:
        now = now or backup.utcnow()
        cfg = load()
        due = next_run(cfg, last_attempt(), now)
        if due is None or now < due:
            return None
        backup.update_state(ftp_last_scheduled_at=now.isoformat())
        return run(cfg, trigger="schedule")


scheduler = Scheduler()
