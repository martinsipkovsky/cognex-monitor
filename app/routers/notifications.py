"""Notification rules, providers, logs and a test-send endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import notifiers
from ..database import get_db
from ..dependencies import require_permission
from ..models import NotificationLog, NotificationProvider, NotificationRule, User
from ..schemas import ProviderCreate, RuleCreate

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_CONDITIONS = {"scrap_rate", "fail_count", "disconnected"}


@router.get("/notifier-kinds")
def notifier_kinds(_: User = Depends(require_permission("manage_notifications"))):
    return notifiers.describe()


# ---- rules ----------------------------------------------------------------
@router.get("/rules")
def list_rules(db: Session = Depends(get_db), _: User = Depends(require_permission("manage_notifications"))):
    return db.query(NotificationRule).order_by(NotificationRule.id).all()


@router.post("/rules", status_code=201)
def create_rule(
    payload: RuleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_notifications")),
):
    if payload.condition not in _CONDITIONS:
        raise HTTPException(400, f"condition must be one of {sorted(_CONDITIONS)}")
    rule = NotificationRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("manage_notifications"))):
    rule = db.get(NotificationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()


# ---- providers ------------------------------------------------------------
@router.get("/providers")
def list_providers(db: Session = Depends(get_db), _: User = Depends(require_permission("manage_notifications"))):
    return db.query(NotificationProvider).order_by(NotificationProvider.id).all()


@router.post("/providers", status_code=201)
def create_provider(
    payload: ProviderCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_notifications")),
):
    if payload.kind not in notifiers.available():
        raise HTTPException(400, f"Unknown notifier kind: {payload.kind}")
    provider = NotificationProvider(**payload.model_dump())
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("manage_notifications"))):
    provider = db.get(NotificationProvider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    db.delete(provider)
    db.commit()


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_notifications")),
):
    provider = db.get(NotificationProvider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    try:
        notifier = notifiers.get_notifier(provider.kind, provider.config)
        notifier.send("Cognex Monitor test notification ✅")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Send failed: {exc}") from exc
    return {"ok": True}


# ---- logs -----------------------------------------------------------------
@router.get("/logs")
def list_logs(limit: int = 100, db: Session = Depends(get_db), _: User = Depends(require_permission("manage_notifications"))):
    rows = db.query(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "message": r.message,
            "delivered": r.delivered,
            "detail": r.detail,
            "created_at": r.created_at,
        }
        for r in rows
    ]
