"""SLMP (Mitsubishi MC protocol, 3E binary frame) client driver.

How Cognex uses SLMP: an In-Sight camera with "SLMP Protocol" / "SLMP
Scanner" enabled is the *client*. It connects to a Mitsubishi PLC (iQ-R, iQ-F,
Q, L series) and writes its results into the PLC's device memory (usually D
or W registers); the camera itself is not an SLMP server you can read. So
there are two ways to get the numbers into this app:

* this driver, ``slmp``: the app is an SLMP client too and polls the **PLC**
  (or any SLMP server) for the registers the camera writes into. Host/Port are
  the PLC's IP and its SLMP port (set in GX Works "Ethernet Configuration",
  binary code, e.g. 5000/5007).
* ``slmp_listen`` (``slmp_server.py``): the app pretends to be the PLC, so the
  camera can write straight into the app when there is no PLC.

Config::

    config = {
        "pass_device": "D100",     # device holding the pass counter
        "fail_device": "D102",     # device holding the fail counter
        "count_device": null,      # optional total counter
        "width": 1,                # 1 = 16-bit word, 2 = 32-bit (2 words, low word first)
        "job_device": null,        # optional: first word of the job name / number
        "job_length": 8,           # words to read for an ASCII job name (2 chars each)
        "job_format": "ascii",     # "ascii" or "number"
        "default_job": "MAIN",     # job name when job_device is not set
        "transport": "tcp",        # "tcp" or "udp", as configured on the PLC
        "network": 0, "pc": 255, "module_io": 1023, "station": 0,   # 3E routing
        "timeout": 3.0
    }

Device names are a letter code plus a number: ``D100``, ``W1A`` (W, B, X, Y,
SW, SB are hexadecimal, as in GX Works), ``R200``, ``ZR1000``, ``M10``. Words
are read with batch read (command 0401, subcommand 0000), which every
MELSEC series that speaks SLMP/MC 3E accepts.

The frame encoder/decoder below is shared with ``slmp_server.py``.
"""
from __future__ import annotations

import re
import socket
import struct

from ..counters import Sample
from .base import ProtocolDriver, ProtocolError

# --------------------------------------------------------------------------- #
# Device codes and address parsing
# --------------------------------------------------------------------------- #

#: name -> (binary device code, number base)
DEVICES: dict[str, tuple[int, int]] = {
    "SM": (0x91, 10), "SD": (0xA9, 10),
    "X": (0x9C, 16), "Y": (0x9D, 16), "M": (0x90, 10), "L": (0x92, 10),
    "F": (0x93, 10), "V": (0x94, 10), "B": (0xA0, 16),
    "D": (0xA8, 10), "W": (0xB4, 16),
    "TS": (0xC1, 10), "TC": (0xC0, 10), "TN": (0xC2, 10),
    "CS": (0xC4, 10), "CC": (0xC3, 10), "CN": (0xC5, 10),
    "SB": (0xA1, 16), "SW": (0xB5, 16),
    "DX": (0xA2, 16), "DY": (0xA3, 16),
    "Z": (0xCC, 10), "R": (0xAF, 10), "ZR": (0xB0, 10),
}
#: bit devices (read as words they come back as 16 packed bits)
BIT_DEVICES = {"SM", "X", "Y", "M", "L", "F", "V", "B", "TS", "TC", "CS", "CC", "SB", "DX", "DY"}
_CODE_TO_NAME = {code: name for name, (code, _) in DEVICES.items()}

_ADDR = re.compile(r"^\s*([A-Za-z]{1,2})\s*([0-9A-Fa-f]+)\s*$")


def parse_device(spec: str) -> tuple[int, int]:
    """'D100' -> (0xA8, 100); 'W1A' -> (0xB4, 26)."""
    m = _ADDR.match(str(spec or ""))
    if not m:
        raise ProtocolError(f"Bad SLMP device {spec!r}; use e.g. D100, W1A, R200")
    letters, number = m.group(1).upper(), m.group(2)
    # 'DX10' vs 'D' + hex-looking number: prefer the longest known name
    if letters not in DEVICES and letters[:1] in DEVICES:
        number, letters = letters[1:] + number, letters[:1]
    if letters not in DEVICES:
        raise ProtocolError(f"Unknown SLMP device {letters!r} in {spec!r}")
    code, base = DEVICES[letters]
    try:
        return code, int(number, base)
    except ValueError as exc:
        raise ProtocolError(f"Bad SLMP device number in {spec!r}") from exc


def device_name(code: int, number: int) -> str:
    name = _CODE_TO_NAME.get(code, f"?{code:02X}")
    base = DEVICES.get(name, (0, 10))[1]
    return f"{name}{number:X}" if base == 16 else f"{name}{number}"


# --------------------------------------------------------------------------- #
# 3E binary frames
# --------------------------------------------------------------------------- #

CMD_READ = 0x0401
CMD_WRITE = 0x1401
SUB_WORD = 0x0000
SUB_BIT = 0x0001

REQ_SUBHEADER = b"\x50\x00"
RES_SUBHEADER = b"\xd0\x00"
#: fixed part of a 3E header: subheader(2) net(1) pc(1) io(2) station(1) length(2)
HEADER_LEN = 9


def _route(network: int, pc: int, module_io: int, station: int) -> bytes:
    return struct.pack("<BBHB", network, pc, module_io, station)


def build_request(command: int, subcommand: int, body: bytes, *, network: int = 0,
                  pc: int = 0xFF, module_io: int = 0x03FF, station: int = 0,
                  timer: int = 0x0010) -> bytes:
    """A complete 3E binary request. ``timer`` is in 250 ms units."""
    payload = struct.pack("<HHH", timer, command, subcommand) + body
    return REQ_SUBHEADER + _route(network, pc, module_io, station) + struct.pack("<H", len(payload)) + payload


def device_spec(code: int, number: int, points: int) -> bytes:
    return number.to_bytes(3, "little") + bytes([code]) + struct.pack("<H", points)


def build_read(code: int, number: int, points: int, **route) -> bytes:
    return build_request(CMD_READ, SUB_WORD, device_spec(code, number, points), **route)


def build_write(code: int, number: int, words: list[int], **route) -> bytes:
    body = device_spec(code, number, len(words)) + b"".join(struct.pack("<H", w & 0xFFFF) for w in words)
    return build_request(CMD_WRITE, SUB_WORD, body, **route)


def build_response(request_route: bytes, end_code: int, data: bytes = b"") -> bytes:
    payload = struct.pack("<H", end_code) + data
    return RES_SUBHEADER + request_route + struct.pack("<H", len(payload)) + payload


def frame_length(buf: bytes | bytearray) -> int | None:
    """Total length of the first frame in ``buf``, or None if incomplete."""
    if len(buf) < HEADER_LEN:
        return None
    return HEADER_LEN + struct.unpack_from("<H", buf, 7)[0]


def parse_response(frame: bytes) -> bytes:
    """Return the data part of a response frame; raise on an error end code."""
    if frame[:2] != RES_SUBHEADER:
        raise ProtocolError(f"Not an SLMP 3E binary response (got {frame[:2].hex()}); "
                            "is the PLC port set to binary code?")
    if len(frame) < HEADER_LEN + 2:
        raise ProtocolError("Truncated SLMP response")
    end_code = struct.unpack_from("<H", frame, HEADER_LEN)[0]
    if end_code:
        raise ProtocolError(f"PLC returned SLMP error end code 0x{end_code:04X}")
    return bytes(frame[HEADER_LEN + 2:])


def words_to_int(words: list[int], width: int) -> int:
    """16- or 32-bit value; 32-bit is low word first (MELSEC convention)."""
    if width == 2:
        return words[0] | (words[1] << 16)
    return words[0]


def words_to_ascii(words: list[int]) -> str:
    """MELSEC strings: two chars per word, low byte first, NUL-terminated."""
    raw = b"".join(struct.pack("<H", w) for w in words)
    return raw.split(b"\x00")[0].decode("ascii", errors="replace").strip()


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


class SlmpDriver(ProtocolDriver):
    key = "slmp"
    label = "SLMP / MC protocol (read PLC registers)"
    config_fields = {
        "pass_device": "Device with the pass counter, e.g. D100",
        "fail_device": "Device with the fail counter, e.g. D102",
        "count_device": "Optional device with a total counter",
        "width": "1 = 16-bit counters, 2 = 32-bit (two words, low word first)",
        "job_device": "Optional first device of the job name or number, e.g. D200",
        "job_length": "Words to read for an ASCII job name (2 chars per word, default 8)",
        "job_format": "'ascii' (job name text) or 'number' (job id)",
        "default_job": "Job name when job_device is not set (default 'MAIN')",
        "transport": "'tcp' (default) or 'udp', as set on the PLC's SLMP port",
        "network": "3E network number (default 0)",
        "pc": "3E PC number (default 255)",
        "module_io": "3E request destination module I/O (default 1023 = 0x03FF, own station)",
        "station": "3E request destination station (default 0)",
        "timeout": "Seconds to wait for the PLC (default 3)",
    }

    def read(self) -> Sample:
        cfg = self.config
        width = 2 if int(cfg.get("width", 1) or 1) == 2 else 1
        with self._connect() as sock:
            raw_pass = self._value(sock, cfg.get("pass_device"), width)
            raw_fail = self._value(sock, cfg.get("fail_device"), width)
            raw_count = self._value(sock, cfg.get("count_device"), width)
            job = self._job(sock)
        return Sample(job_name=job, raw_pass=raw_pass, raw_fail=raw_fail,
                      raw_count=raw_count, extra={"plc": f"{self.host}:{self.port}"})

    # ---- helpers ---------------------------------------------------------
    def _route(self) -> dict:
        cfg = self.config
        return {
            "network": int(cfg.get("network", 0) or 0),
            "pc": int(cfg.get("pc", 0xFF) if cfg.get("pc") is not None else 0xFF),
            "module_io": int(cfg.get("module_io", 0x03FF) if cfg.get("module_io") is not None else 0x03FF),
            "station": int(cfg.get("station", 0) or 0),
        }

    def _connect(self) -> socket.socket:
        timeout = float(self.config.get("timeout", 3.0) or 3.0)
        udp = str(self.config.get("transport", "tcp")).lower() == "udp"
        try:
            if udp:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(timeout)
                sock.connect((self.host, self.port))
            else:
                sock = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as exc:
            raise ProtocolError(f"Could not connect to SLMP device {self.host}:{self.port}: {exc}") from exc
        self._udp = udp
        return sock

    def read_words(self, sock: socket.socket, device: str, points: int) -> list[int]:
        code, number = parse_device(device)
        try:
            sock.sendall(build_read(code, number, points, **self._route()))
            frame = self._recv_frame(sock)
        except OSError as exc:
            raise ProtocolError(f"SLMP read of {device} failed: {exc}") from exc
        data = parse_response(frame)
        if len(data) < points * 2:
            raise ProtocolError(f"SLMP read of {device}: expected {points} words, got {len(data) // 2}")
        return list(struct.unpack(f"<{points}H", data[: points * 2]))

    def _recv_frame(self, sock: socket.socket) -> bytes:
        if getattr(self, "_udp", False):
            return sock.recv(65535)
        buf = bytearray()
        while True:
            need = frame_length(buf)
            if need is not None and len(buf) >= need:
                return bytes(buf[:need])
            chunk = sock.recv(4096)
            if not chunk:
                raise ProtocolError("PLC closed the SLMP connection")
            buf.extend(chunk)

    def _value(self, sock, device, width: int) -> int:
        if device in (None, ""):
            return 0
        return words_to_int(self.read_words(sock, str(device), width), width)

    def _job(self, sock) -> str:
        cfg = self.config
        default = cfg.get("default_job") or "MAIN"
        device = cfg.get("job_device")
        if device in (None, ""):
            return default
        if str(cfg.get("job_format", "ascii")).lower() == "number":
            return str(self.read_words(sock, str(device), 1)[0])
        length = max(1, min(int(cfg.get("job_length", 8) or 8), 64))
        return words_to_ascii(self.read_words(sock, str(device), length)) or default
