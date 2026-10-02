"""Notifier contract. Each notifier is one file, like the protocols."""
from __future__ import annotations

from abc import ABC, abstractmethod


class NotifierError(Exception):
    pass


class Notifier(ABC):
    key: str = ""
    label: str = ""
    config_fields: dict[str, str] = {}
    # pre-filled in the Add provider dialog
    config_example: dict = {}

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def send(self, message: str) -> None:
        """Deliver a message or raise NotifierError."""
        raise NotImplementedError
