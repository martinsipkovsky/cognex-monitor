"""Protocol driver contract.

Every camera protocol lives in its own file in this package and subclasses
``ProtocolDriver``. To troubleshoot one protocol you open exactly one file.

A driver's only job is: connect to the camera, read one sample, normalise it
into a ``counters.Sample``, and disconnect. Accumulation, persistence and
scheduling are handled elsewhere (app.counters / app.poller).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..counters import Sample


class ProtocolError(Exception):
    """Raised by a driver when it cannot talk to the camera."""


class ProtocolDriver(ABC):
    #: unique key stored on Device.protocol
    key: str = ""
    #: human label shown in the UI
    label: str = ""
    #: description of the ``config`` dict this driver accepts, for the UI form
    config_fields: dict[str, str] = {}

    def __init__(self, host: str, port: int, config: dict | None = None):
        self.host = host
        self.port = port
        self.config = config or {}

    @abstractmethod
    def read(self) -> Sample:
        """Open a connection, read one sample, return it. Raise ProtocolError."""
        raise NotImplementedError

    # Optional lifecycle hooks for drivers that keep a persistent socket.
    def open(self) -> None:  # pragma: no cover - default no-op
        pass

    def close(self) -> None:  # pragma: no cover - default no-op
        pass
