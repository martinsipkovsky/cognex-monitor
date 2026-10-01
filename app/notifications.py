"""Notification rule evaluation and dispatch.

Called by the poller after each device update. Evaluates every enabled rule
against the device's current state, respects each rule's cooldown, delivers
through every enabled provider, and logs the outcome.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from . import notifiers, production
from .models import (
    CounterState,
    Device,
    NotificationLog,
    NotificationProvider,
    NotificationRule,
    utcnow,
)


def _cooldown_ok(rule: NotificationRule, now: dt.datetime) -> bool:
    if rule.last_fired_at is None:
        return True
    last = rule.last_fired_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=dt.timezone.utc)
    return (now - last).total_seconds() >= rule.cooldown


def _condition_met(rule: NotificationRule, device: Device, state: CounterState | None) -> tuple[bool, str]:
    if rule.condition == "disconnected":
        if not device.connected:
            return True, f"Camera '{device.name}' is disconnected: {device.last_error or 'no data'}"
        return False, ""

    if state is None:
        return False, ""

    # A camera that is not in production (idle or stopped by an operator) only
    # produces false NOK signals, so counter-based alerts are not sent for it.
    if not production.in_production(device):
        return False, ""

    if rule.condition == "scrap_rate":
        if state.total_count > 0 and state.scrap_rate >= rule.threshold:
            pct = state.scrap_rate * 100
            return True, (
                f"High scrap on '{device.name}' job '{state.job_name}': "
                f"{pct:.1f}% ({state.total_fail}/{state.total_count}) "
                f">= {rule.threshold * 100:.1f}%"
            )
        return False, ""

    if rule.condition == "fail_count":
        if state.total_fail >= rule.threshold:
            return True, (
                f"Fail count on '{device.name}' job '{state.job_name}' "
                f"reached {state.total_fail} (>= {int(rule.threshold)})"
            )
        return False, ""

    return False, ""


def dispatch(db: Session, message: str, rule_id: int | None = None) -> None:
    """Send one message through every enabled provider and log each result."""
    providers = db.query(NotificationProvider).filter(NotificationProvider.enabled.is_(True)).all()
    if not providers:
        db.add(NotificationLog(rule_id=rule_id, message=message, delivered=False, detail="no enabled providers"))
        db.commit()
        return

    for provider in providers:
        detail = "ok"
        delivered = True
        try:
            notifier = notifiers.get_notifier(provider.kind, provider.config)
            notifier.send(message)
        except Exception as exc:  # noqa: BLE001 - record every failure
            delivered = False
            detail = f"{provider.name}: {exc}"
        db.add(
            NotificationLog(
                rule_id=rule_id,
                message=message,
                delivered=delivered,
                detail=f"{provider.name}: {detail}" if delivered else detail,
            )
        )
    db.commit()


def evaluate_device(db: Session, device: Device) -> None:
    """Check all rules that apply to a device and fire the ones that match."""
    now = utcnow()
    active_state = (
        db.query(CounterState)
        .filter(CounterState.device_id == device.id, CounterState.is_active.is_(True))
        .first()
    )
    rules = (
        db.query(NotificationRule)
        .filter(
            NotificationRule.enabled.is_(True),
            (NotificationRule.device_id == device.id) | (NotificationRule.device_id.is_(None)),
        )
        .all()
    )
    for rule in rules:
        met, message = _condition_met(rule, device, active_state)
        if met and _cooldown_ok(rule, now):
            dispatch(db, message, rule_id=rule.id)
            rule.last_fired_at = now
            db.commit()
