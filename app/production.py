"""Production state of a camera: running, idle (auto-stopped) or stopped.

* running  - the pass counter increased within the camera's idle timeout.
* idle     - no pass increase for idle_timeout_min minutes. The line is most
             likely not producing, so NOK counts are treated as false signals
             (dashboard grays the camera, scrap alerts are suppressed). It goes
             back to running by itself as soon as the pass counter increases.
* stopped  - an operator pressed Stop. Stays stopped until Start is pressed,
             even if counts keep arriving.

Start clears a manual stop and restarts the idle clock, so a camera that
still does not count will fall back to idle after its timeout.
"""
from __future__ import annotations

import datetime as dt

from .models import Device, utcnow

RUNNING = "running"
IDLE = "idle"
STOPPED = "stopped"

DEFAULT_IDLE_TIMEOUT_MIN = 30


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def state(device: Device, now: dt.datetime | None = None) -> str:
    if device.manual_stop:
        return STOPPED
    last = _aware(device.last_pass_change_at)
    if last is None:
        return IDLE
    now = now or utcnow()
    timeout = max(1, device.idle_timeout_min or DEFAULT_IDLE_TIMEOUT_MIN)
    if (now - last).total_seconds() >= timeout * 60:
        return IDLE
    return RUNNING


def in_production(device: Device, now: dt.datetime | None = None) -> bool:
    return state(device, now) == RUNNING


def describe(device: Device, now: dt.datetime | None = None) -> dict:
    """Fields the API returns about a camera's production state."""
    return {
        "production_state": state(device, now),
        "in_production": in_production(device, now),
        "manual_stop": bool(device.manual_stop),
        "idle_timeout_min": device.idle_timeout_min or DEFAULT_IDLE_TIMEOUT_MIN,
        "last_pass_change_at": _aware(device.last_pass_change_at),
    }


def note_pass_increase(device: Device, now: dt.datetime | None = None) -> None:
    """Called by the poller whenever the pass counter went up."""
    device.last_pass_change_at = now or utcnow()


def start(device: Device) -> None:
    device.manual_stop = False
    device.last_pass_change_at = utcnow()


def stop(device: Device) -> None:
    device.manual_stop = True
