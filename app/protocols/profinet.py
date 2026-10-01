"""PROFINET driver — honest, limited support.

Read this before relying on it in production:

PROFINET IO is a real-time, cyclic Ethernet protocol built on a layered stack
(DCP for device discovery, the RT/IRT cyclic data channel over raw Ethernet
frames, and acyclic DCE/RPC for parameters). A camera acts as an IO-device and
a PLC acts as the IO-controller; the two establish an Application Relation and
then exchange process data every few milliseconds over raw layer-2 frames.

A pure-Python, user-space implementation **cannot** be a full IO-controller:
that needs raw-socket / layer-2 access, precise cyclic timing, and the GSDML
module configuration the PLC normally owns. So this driver does **not** speak
native PROFINET RT.

What it *does* offer, so the protocol is still usable through this app:

* **gateway mode** (recommended): read the camera's process data from a
  PROFINET-to-Modbus/TCP gateway or from the controlling PLC's data blocks
  exposed over Modbus/TCP. You point this driver at that endpoint and it
  delegates to the Modbus driver. This is how most SCADA systems ingest
  PROFINET counters in practice.

* **explicit "unsupported"**: if configured for native mode it raises a clear
  ProtocolError rather than pretending to work.

    config = {
        "mode": "gateway",         # only "gateway" is functional
        "gateway_host": "10.0.0.5",# Modbus/TCP endpoint exposing the PN data
        "gateway_port": 502,
        "modbus": { ... }          # same config shape as the Modbus driver
    }
"""
from __future__ import annotations

from ..counters import Sample
from .base import ProtocolDriver, ProtocolError
from .modbus import ModbusDriver


class ProfinetDriver(ProtocolDriver):
    key = "profinet"
    label = "PROFINET (via gateway)"
    config_fields = {
        "mode": "'gateway' (functional, delegates to Modbus/TCP) — native RT is not supported",
        "gateway_host": "Host of the PROFINET->Modbus/TCP gateway or PLC data endpoint",
        "gateway_port": "Port of that gateway (default 502)",
        "modbus": "Modbus register map (see the Modbus driver's config fields)",
    }

    def read(self) -> Sample:
        mode = self.config.get("mode", "gateway")
        if mode != "gateway":
            raise ProtocolError(
                "Native PROFINET RT is not supported by this pure-Python app. "
                "Use mode='gateway' with a PROFINET-to-Modbus/TCP gateway, or "
                "read the counters from the controlling PLC over Modbus/TCP."
            )

        host = self.config.get("gateway_host") or self.host
        port = int(self.config.get("gateway_port", 502))
        modbus_cfg = self.config.get("modbus", {})
        driver = ModbusDriver(host=host, port=port, config=modbus_cfg)
        sample = driver.read()
        sample.extra = {**(sample.extra or {}), "via": "profinet-gateway"}
        return sample
