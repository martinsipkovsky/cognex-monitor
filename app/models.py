"""Database models.

Design notes on the counter logic (the heart of this app):

* Each Device has a live CounterState per job name. The camera exposes its own
  pass/fail counters which operators may reset at any time. We never want to
  lose counts across a reset, so every poll we compute the *delta* since the
  previous reading and add it to a running global total.
* A camera reset is detected when a raw counter drops below the value we saw
  last time. In that case the delta is the new raw value itself (the camera
  restarted from zero), not raw_now - raw_prev (which would be negative).
* When the job name changes, the running totals for the previous job are
  frozen (kept in the DB) and a fresh CounterState starts for the new job.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- #
# Users, roles and permissions
# --------------------------------------------------------------------------- #

# Granular permission keys. Admin implicitly has all of them.
PERMISSIONS = {
    "view_dashboard": "View dashboards and camera data",
    "manage_devices": "Create, edit and delete camera devices",
    "control_connections": "Start/stop camera connections and polling",
    "view_data": "Browse logged readings and counters",
    "manage_notifications": "Configure notification rules and providers",
    "manage_users": "Create users and edit their permissions",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # list[str] of permission keys; ignored when is_admin is True
    permissions: Mapped[list] = mapped_column(JSON, default=list)

    def has_permission(self, key: str) -> bool:
        if self.is_admin:
            return True
        return key in (self.permissions or [])


# --------------------------------------------------------------------------- #
# Devices (cameras)
# --------------------------------------------------------------------------- #


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=23)

    # one of the keys in app.protocols.registry.available()
    protocol: Mapped[str] = mapped_column(String(40))
    # protocol-specific settings (register addresses, telegram layout, ...)
    protocol_config: Mapped[dict] = mapped_column(JSON, default=dict)

    poll_interval: Mapped[int] = mapped_column(Integer, default=5)  # seconds
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # updated by the poller
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_poll_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_job: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Production state (see app.production). A camera is in production until
    # its pass counter has not increased for idle_timeout_min minutes; an
    # operator can also stop it by hand (manual_stop) until Start is pressed.
    idle_timeout_min: Mapped[int] = mapped_column(Integer, default=30)
    manual_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    last_pass_change_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    counters: Mapped[list["CounterState"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    readings: Mapped[list["Reading"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    @property
    def production_state(self) -> str:
        from . import production  # local import: production imports this module

        return production.state(self)


class CounterState(Base):
    """Running, reset-proof totals for a (device, job) pair."""

    __tablename__ = "counter_states"
    __table_args__ = (UniqueConstraint("device_id", "job_name", name="uq_device_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    job_name: Mapped[str] = mapped_column(String(255), index=True)

    # accumulated totals that survive camera-side counter resets
    total_pass: Mapped[int] = mapped_column(Integer, default=0)
    total_fail: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)

    # last raw values read from the camera, used for delta/reset detection
    last_raw_pass: Mapped[int] = mapped_column(Integer, default=0)
    last_raw_fail: Mapped[int] = mapped_column(Integer, default=0)
    last_raw_count: Mapped[int] = mapped_column(Integer, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    device: Mapped["Device"] = relationship(back_populates="counters")

    @property
    def scrap_rate(self) -> float:
        if self.total_count <= 0:
            return 0.0
        return self.total_fail / self.total_count


class Reading(Base):
    """A raw snapshot from one poll, kept for history/audit."""

    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    job_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    raw_pass: Mapped[int] = mapped_column(Integer, default=0)
    raw_fail: Mapped[int] = mapped_column(Integer, default=0)
    raw_count: Mapped[int] = mapped_column(Integer, default=0)

    # the running totals at the moment of this reading
    total_pass: Mapped[int] = mapped_column(Integer, default=0)
    total_fail: Mapped[int] = mapped_column(Integer, default=0)

    # everything else the protocol returned (jobname, custom tags, ...)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    device: Mapped["Device"] = relationship(back_populates="readings")


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    device_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devices.id"), nullable=True
    )  # null = applies to all devices

    # "scrap_rate" | "fail_count" | "disconnected"
    condition: Mapped[str] = mapped_column(String(40))
    # e.g. 0.05 for 5% scrap, or a fail-count threshold, or minutes offline
    threshold: Mapped[float] = mapped_column(default=0.0)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # minimum seconds between two alerts for the same rule
    cooldown: Mapped[int] = mapped_column(Integer, default=300)
    last_fired_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationProvider(Base):
    """Configured notifier, e.g. a WhatsApp group bridge."""

    __tablename__ = "notification_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))  # key in app.notifiers.registry
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    message: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
