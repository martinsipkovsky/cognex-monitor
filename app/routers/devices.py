"""Device (camera) CRUD, protocol metadata, manual poll/test, production
start/stop, and export/import of camera configurations."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import production, protocols
from ..config import settings
from ..database import get_db
from ..dependencies import require_api_user, require_permission
from ..models import CounterState, Device, User
from ..poller import poll_device_once
from ..protocols.tcp_listener import parse_port_range
from ..schemas import DeviceCreate, DeviceExportItem, DeviceImport, DeviceOut, DeviceUpdate

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("/protocols")
def protocol_catalog(_: User = Depends(require_api_user)):
    return protocols.describe()


@router.get("/listen-ports")
def listen_ports(_: User = Depends(require_api_user)):
    """Port range published for cameras that push data to the app."""
    lo, hi = parse_port_range(settings.listen_ports)
    return {"first": lo, "last": hi}


def _check_listen_port(db: Session, protocol: str, port: int, device_id: int | None = None) -> None:
    """A pushing camera needs a free port inside the published range."""
    if not protocols.is_push(protocol):
        return
    lo, hi = parse_port_range(settings.listen_ports)
    if not lo <= port <= hi:
        raise HTTPException(
            400,
            f"Listen port must be between {lo} and {hi} (the ports published in "
            f"docker-compose, LISTEN_PORTS). Got {port}.",
        )
    clash = (
        db.query(Device)
        .filter(
            Device.protocol.in_(protocols.push_keys()),
            Device.port == port,
            Device.id != (device_id or 0),
        )
        .first()
    )
    if clash:
        raise HTTPException(409, f"Port {port} is already used by camera '{clash.name}'")


EXPORT_FIELDS = tuple(DeviceExportItem.model_fields)


@router.get("/export")
def export_devices(db: Session = Depends(get_db), _: User = Depends(require_permission("view_dashboard"))):
    """All camera configurations as a downloadable JSON file (no counter history)."""
    cameras = [
        {f: getattr(d, f) for f in EXPORT_FIELDS}
        for d in db.query(Device).order_by(Device.name).all()
    ]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return JSONResponse(
        {"version": 1, "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(), "cameras": cameras},
        headers={"Content-Disposition": f'attachment; filename="cognex-cameras-{stamp}.json"'},
    )


@router.post("/import")
def import_devices(
    payload: DeviceImport,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_devices")),
):
    """Add cameras from an export file; a camera with the same name is updated.

    All or nothing: if any camera in the file is invalid, nothing is changed and
    every problem is reported.
    """
    names = [c.name for c in payload.cameras]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise HTTPException(400, "The file lists these cameras more than once: " + ", ".join(dupes))

    created, updated, errors = [], [], []
    for item in payload.cameras:
        data = item.model_dump()
        if item.protocol not in protocols.available():
            errors.append(f"{item.name}: unknown protocol '{item.protocol}'")
            continue
        device = db.query(Device).filter(Device.name == item.name).first()
        try:
            _check_listen_port(db, item.protocol, item.port, device.id if device else None)
        except HTTPException as exc:
            errors.append(f"{item.name}: {exc.detail}")
            continue
        if device is None:
            db.add(Device(**data))
            created.append(item.name)
        else:
            for key, value in data.items():
                setattr(device, key, value)
            updated.append(item.name)
        db.flush()  # so later cameras in the file see this one's port

    if errors:
        db.rollback()
        raise HTTPException(400, "Nothing was imported. " + "; ".join(errors))
    db.commit()
    return {"created": created, "updated": updated}


@router.get("", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db), _: User = Depends(require_permission("view_dashboard"))):
    return db.query(Device).order_by(Device.name).all()


@router.post("", response_model=DeviceOut, status_code=201)
def create_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_devices")),
):
    if payload.protocol not in protocols.available():
        raise HTTPException(400, f"Unknown protocol: {payload.protocol}")
    if db.query(Device).filter(Device.name == payload.name).first():
        raise HTTPException(409, "A device with that name already exists")
    _check_listen_port(db, payload.protocol, payload.port)
    device = Device(**payload.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: int,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_devices")),
):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    data = payload.model_dump(exclude_unset=True)
    if "protocol" in data and data["protocol"] not in protocols.available():
        raise HTTPException(400, f"Unknown protocol: {data['protocol']}")
    _check_listen_port(db, data.get("protocol", device.protocol), data.get("port", device.port), device.id)
    for key, value in data.items():
        setattr(device, key, value)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204)
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_devices")),
):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    db.delete(device)
    db.commit()


@router.post("/{device_id}/poll")
def poll_now(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("control_connections")),
):
    """Read the camera once, right now. Useful to test configuration."""
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    if protocols.is_push(device.protocol):
        raise HTTPException(
            400,
            f"This camera pushes its data to the app on port {device.port}; it cannot be polled. "
            + ("It is connected." if device.connected else (device.last_error or "")),
        )
    try:
        reading = poll_device_once(db, device)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        device.connected = False
        device.last_error = str(exc)
        db.commit()
        raise HTTPException(502, f"Read failed: {exc}") from exc
    return {
        "job": reading.job_name,
        "raw_pass": reading.raw_pass,
        "raw_fail": reading.raw_fail,
        "total_pass": reading.total_pass,
        "total_fail": reading.total_fail,
        "extra": reading.extra,
    }


def _set_production(db: Session, device_id: int, running: bool) -> dict:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    if running:
        production.start(device)
    else:
        production.stop(device)
    db.commit()
    return production.describe(device)


@router.post("/{device_id}/production/start")
def production_start(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("control_connections")),
):
    """Put the camera back in production now (clears a manual stop)."""
    return _set_production(db, device_id, True)


@router.post("/{device_id}/production/stop")
def production_stop(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("control_connections")),
):
    """Mark the camera as not in production until Start is pressed."""
    return _set_production(db, device_id, False)


@router.get("/{device_id}/counters")
def device_counters(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("view_data")),
):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    states = (
        db.query(CounterState)
        .filter(CounterState.device_id == device_id)
        .order_by(CounterState.is_active.desc(), CounterState.updated_at.desc())
        .all()
    )
    return [
        {
            "job_name": s.job_name,
            "total_pass": s.total_pass,
            "total_fail": s.total_fail,
            "total_count": s.total_count,
            "scrap_rate": round(s.scrap_rate, 4),
            "is_active": s.is_active,
            "updated_at": s.updated_at,
        }
        for s in states
    ]
