"""Generic TCP / Cognex Native Mode command driver.

Two common uses:

1. **Native Mode**: In-Sight cameras answer ASCII commands over a telnet-style
   socket (after a login handshake). You configure which command reads which
   cell, and the driver issues them and parses the replies.

2. **Generic request/response**: send a fixed request string, read the reply,
   and pull counters out of it with regular expressions.

Config::

    config = {
        "login": "admin",          # Native Mode login (optional)
        "password": "",            # Native Mode password (optional)
        "requests": {              # what to send to read each value
            "job":   "GVJobName",   # Native Mode "Get Value" style, or raw cmd
            "pass":  "GVPassCount",
            "fail":  "GVFailCount"
        },
        "pattern_pass": "(\\d+)",    # regex to extract the number from a reply
        "pattern_fail": "(\\d+)",
        "pattern_job":  "(.+)",
        "timeout": 5.0
    }

This driver is intentionally forgiving: if a command fails it contributes 0
rather than aborting the whole read, so a partially-configured camera still
reports what it can.
"""
from __future__ import annotations

import re
import socket

from ..counters import Sample
from .base import ProtocolDriver, ProtocolError


class TcpDriver(ProtocolDriver):
    key = "tcp"
    label = "Generic TCP / Native Mode"
    config_fields = {
        "login": "Native Mode login user (optional)",
        "password": "Native Mode password (optional)",
        "requests": "Map of job/pass/fail -> command string to send",
        "pattern_pass": "Regex with one group to extract the pass number",
        "pattern_fail": "Regex with one group to extract the fail number",
        "pattern_job": "Regex with one group to extract the job name",
        "timeout": "Socket timeout in seconds",
    }

    def read(self) -> Sample:
        cfg = self.config
        timeout = float(cfg.get("timeout", 5.0))
        requests = cfg.get("requests", {})

        try:
            with socket.create_connection((self.host, self.port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                self._maybe_login(sock, cfg)
                job_reply = self._exchange(sock, requests.get("job"))
                pass_reply = self._exchange(sock, requests.get("pass"))
                fail_reply = self._exchange(sock, requests.get("fail"))
        except (OSError, socket.timeout) as exc:
            raise ProtocolError(f"TCP read failed: {exc}") from exc

        job = self._extract_str(job_reply, cfg.get("pattern_job", r"(.+)")) or cfg.get("default_job", "MAIN")
        raw_pass = self._extract_int(pass_reply, cfg.get("pattern_pass", r"(\d+)"))
        raw_fail = self._extract_int(fail_reply, cfg.get("pattern_fail", r"(\d+)"))
        return Sample(
            job_name=job.strip(),
            raw_pass=raw_pass,
            raw_fail=raw_fail,
            extra={"job_reply": job_reply, "pass_reply": pass_reply, "fail_reply": fail_reply},
        )

    def _maybe_login(self, sock: socket.socket, cfg: dict) -> None:
        login = cfg.get("login")
        if not login:
            return
        # Native Mode: server prompts for user then password.
        self._recv(sock)
        sock.sendall((login + "\r\n").encode())
        self._recv(sock)
        sock.sendall(((cfg.get("password") or "") + "\r\n").encode())
        self._recv(sock)

    def _exchange(self, sock: socket.socket, command) -> str:
        if not command:
            return ""
        sock.sendall((command + "\r\n").encode())
        return self._recv(sock)

    @staticmethod
    def _recv(sock: socket.socket, size: int = 2048) -> str:
        try:
            return sock.recv(size).decode("ascii", errors="replace")
        except socket.timeout:
            return ""

    @staticmethod
    def _extract_int(text: str, pattern: str) -> int:
        m = re.search(pattern, text or "")
        if not m:
            return 0
        try:
            return int(float(m.group(1)))
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def _extract_str(text: str, pattern: str) -> str:
        m = re.search(pattern, (text or "").strip())
        return m.group(1).strip() if m else ""
