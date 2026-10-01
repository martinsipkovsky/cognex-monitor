"""Pydantic request/response models for the JSON API."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---- Users ----------------------------------------------------------------
class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)
    is_admin: bool = False
    permissions: list[str] = []


class UserUpdate(BaseModel):
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    permissions: Optional[list[str]] = None


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    permissions: list[str]

    model_config = ConfigDict(from_attributes=True)


# ---- Devices --------------------------------------------------------------
class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host: str
    port: int = 23
    protocol: str
    protocol_config: dict = {}
    poll_interval: int = 5
    enabled: bool = True
    # minutes without a pass increase before the camera counts as not in production
    idle_timeout_min: int = Field(default=30, ge=1, le=10080)


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None
    protocol_config: Optional[dict] = None
    poll_interval: Optional[int] = None
    enabled: Optional[bool] = None
    idle_timeout_min: Optional[int] = Field(default=None, ge=1, le=10080)


class DeviceOut(BaseModel):
    id: int
    name: str
    host: str
    port: int
    protocol: str
    protocol_config: dict
    poll_interval: int
    enabled: bool
    connected: bool
    last_error: Optional[str]
    current_job: Optional[str]
    idle_timeout_min: int
    manual_stop: bool
    production_state: str
    last_pass_change_at: Optional[dt.datetime]

    model_config = ConfigDict(from_attributes=True)


class DeviceExportItem(BaseModel):
    """One camera in an export file: configuration only, no counters/history."""

    name: str = Field(min_length=1, max_length=120)
    host: str = ""
    port: int = 23
    protocol: str
    protocol_config: dict = {}
    poll_interval: int = 5
    enabled: bool = True
    idle_timeout_min: int = Field(default=30, ge=1, le=10080)


class DeviceImport(BaseModel):
    version: int = 1
    cameras: list[DeviceExportItem]


# ---- Notifications --------------------------------------------------------
class RuleCreate(BaseModel):
    name: str
    device_id: Optional[int] = None
    condition: str
    threshold: float = 0.0
    enabled: bool = True
    cooldown: int = 300


class ProviderCreate(BaseModel):
    name: str
    kind: str
    config: dict = {}
    enabled: bool = True
