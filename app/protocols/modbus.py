"""Modbus/TCP driver for Cognex cameras.

Cognex In-Sight supports Modbus/TCP as a slave. Counters are exposed as
holding registers; the exact addresses depend on how the camera's spreadsheet
maps cells to Modbus. The register map is therefore configurable:

    config = {
        "unit_id": 1,
        "pass_register": 0,        # holding register address of pass counter
        "fail_register": 1,
        "count_register": null,    # optional total counter
        "reg_width": 2,            # 1 = 16-bit, 2 = 32-bit (two registers)
        "word_order": "big",       # "big" or "little" for 32-bit values
        "job_registers": [10, 20], # optional: registers holding the job name
                                   #   as ASCII (2 chars per register)
        "job_string": "MAIN",      # or a fixed job name if the camera has one job
        "timeout": 3.0
    }

Requires pymodbus (declared in requirements.txt). If it is not installed the
import error surfaces as a ProtocolError with a clear message.
"""
from __future__ import annotations

from ..counters import Sample
from .base import ProtocolDriver, ProtocolError


class ModbusDriver(ProtocolDriver):
    key = "modbus"
    label = "Modbus/TCP"
    config_fields = {
        "unit_id": "Modbus unit/slave id (default 1)",
        "pass_register": "Holding-register address of the pass counter",
        "fail_register": "Holding-register address of the fail counter",
        "count_register": "Optional holding-register address of a total counter",
        "reg_width": "1 for 16-bit counters, 2 for 32-bit (two registers)",
        "word_order": "'big' or 'little' word order for 32-bit values",
        "job_registers": "Optional [start, end] registers holding the job name as ASCII",
        "job_string": "Fixed job name if the camera runs a single job",
        "timeout": "Connection timeout in seconds",
    }

    def read(self) -> Sample:
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:  # pragma: no cover
            raise ProtocolError(
                "pymodbus is not installed (pip install pymodbus)"
            ) from exc

        cfg = self.config
        unit = int(cfg.get("unit_id", 1))
        width = int(cfg.get("reg_width", 1))
        timeout = float(cfg.get("timeout", 3.0))

        client = ModbusTcpClient(self.host, port=self.port, timeout=timeout)
        if not client.connect():
            raise ProtocolError(f"Could not connect to Modbus device {self.host}:{self.port}")
        try:
            raw_pass = self._read_counter(client, cfg.get("pass_register"), unit, width)
            raw_fail = self._read_counter(client, cfg.get("fail_register"), unit, width)
            count_reg = cfg.get("count_register")
            raw_count = self._read_counter(client, count_reg, unit, width) if count_reg is not None else 0
            job = self._read_job(client, cfg, unit)
        except ProtocolError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise driver errors
            raise ProtocolError(f"Modbus read error: {exc}") from exc
        finally:
            client.close()

        return Sample(
            job_name=job,
            raw_pass=raw_pass,
            raw_fail=raw_fail,
            raw_count=raw_count,
            extra={"unit": unit},
        )

    def _read_counter(self, client, address, unit: int, width: int) -> int:
        if address is None:
            return 0
        address = int(address)
        count = 2 if width == 2 else 1
        rr = client.read_holding_registers(address=address, count=count, slave=unit)
        if rr.isError():
            raise ProtocolError(f"Modbus error reading register {address}: {rr}")
        regs = rr.registers
        if width == 2 and len(regs) == 2:
            hi, lo = (regs[0], regs[1]) if self.config.get("word_order", "big") == "big" else (regs[1], regs[0])
            return (hi << 16) | lo
        return regs[0]

    def _read_job(self, client, cfg: dict, unit: int) -> str:
        if cfg.get("job_string"):
            return str(cfg["job_string"])
        job_regs = cfg.get("job_registers")
        if not job_regs or len(job_regs) != 2:
            return cfg.get("default_job", "MAIN")
        start, end = int(job_regs[0]), int(job_regs[1])
        count = max(1, end - start + 1)
        rr = client.read_holding_registers(address=start, count=count, slave=unit)
        if rr.isError():
            return cfg.get("default_job", "MAIN")
        chars = []
        for reg in rr.registers:
            chars.append(chr((reg >> 8) & 0xFF))
            chars.append(chr(reg & 0xFF))
        name = "".join(chars).split("\x00")[0].strip()
        return name or cfg.get("default_job", "MAIN")
