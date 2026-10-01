"""Cognex In-Sight Data Channel / Native Mode (TCP) driver.

Cognex In-Sight cameras can push a formatted telegram over TCP (the "Data
Channel") or answer Native Mode commands. This driver supports the common
setup where the camera is configured (in In-Sight Explorer, under
Communication -> Data Channel / TCP/IP) to emit one ASCII record per
inspection, with fields separated by a delimiter (comma by default) and each
record terminated by CR/LF.

Because every integrator lays the telegram out differently, the field
positions are configurable rather than hard-coded:

    config = {
        "delimiter": ",",          # field separator in the telegram
        "terminator": "\\r\\n",     # record terminator
        "job_field": 0,            # index of the job/inspection name
        "pass_field": 1,           # index of the pass counter
        "fail_field": 2,           # index of the fail counter
        "count_field": null,       # optional index of a total counter
        "read_timeout": 5.0
    }

If the telegram is a single line with just a status ("Pass"/"Fail") rather
than counters, set ``mode = "event"`` and the driver counts events itself by
returning 1/0 increments; the accumulator upstream turns those into totals.
"""
from __future__ import annotations

import socket

from ..counters import Sample
from .base import ProtocolDriver, ProtocolError


def _to_int(value: str) -> int:
    value = value.strip()
    if not value:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


class DataChannelDriver(ProtocolDriver):
    key = "datachannel"
    label = "Cognex Data Channel (TCP)"
    config_fields = {
        "delimiter": "Field separator in the telegram (default ',')",
        "terminator": "Record terminator (default CRLF)",
        "job_field": "Zero-based index of the job name field",
        "pass_field": "Zero-based index of the pass counter",
        "fail_field": "Zero-based index of the fail counter",
        "count_field": "Optional index of a total-count field",
        "mode": "'counter' (telegram carries totals) or 'event' (one record per part)",
        "read_timeout": "Socket read timeout in seconds",
    }

    def read(self) -> Sample:
        cfg = self.config
        delimiter = cfg.get("delimiter", ",")
        terminator = cfg.get("terminator", "\r\n").encode().decode("unicode_escape")
        timeout = float(cfg.get("read_timeout", 5.0))
        mode = cfg.get("mode", "counter")

        try:
            with socket.create_connection((self.host, self.port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                buf = self._read_record(sock, terminator.encode())
        except (OSError, socket.timeout) as exc:
            raise ProtocolError(f"Data Channel read failed: {exc}") from exc

        line = buf.decode("ascii", errors="replace").strip()
        fields = [f.strip() for f in line.split(delimiter)]

        job = self._field(fields, cfg.get("job_field", 0), default="")
        if not job:
            job = cfg.get("default_job", "UNKNOWN")

        if mode == "event":
            status = self._field(fields, cfg.get("status_field", 1), default="").lower()
            is_pass = status in ("pass", "p", "1", "ok", "good")
            return Sample(
                job_name=job,
                raw_pass=1 if is_pass else 0,
                raw_fail=0 if is_pass else 1,
                extra={"raw": line, "mode": "event"},
            )

        raw_pass = _to_int(self._field(fields, cfg.get("pass_field", 1)))
        raw_fail = _to_int(self._field(fields, cfg.get("fail_field", 2)))
        count_field = cfg.get("count_field")
        raw_count = _to_int(self._field(fields, count_field)) if count_field is not None else 0
        return Sample(
            job_name=job,
            raw_pass=raw_pass,
            raw_fail=raw_fail,
            raw_count=raw_count,
            extra={"raw": line},
        )

    @staticmethod
    def _field(fields: list[str], index, default: str = "0") -> str:
        if index is None:
            return default
        try:
            return fields[int(index)]
        except (IndexError, ValueError, TypeError):
            return default

    @staticmethod
    def _read_record(sock: socket.socket, terminator: bytes, limit: int = 4096) -> bytes:
        """Read until the record terminator or a size cap."""
        data = bytearray()
        while terminator not in data and len(data) < limit:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data.extend(chunk)
        idx = data.find(terminator)
        return bytes(data[:idx]) if idx != -1 else bytes(data)
