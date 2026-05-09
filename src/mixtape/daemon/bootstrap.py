"""Daemon discovery file — written by the running daemon at start, read
by every client to find the port + bearer token. Lives at
``STATE_DIR/api.json``.

Atomic write semantics: write to ``api.json.tmp`` then rename so a
client mid-read never sees a half-written file. Removed in the
daemon's shutdown handler (best-effort — a SIGKILL leaves it stale,
in which case the client's HTTP probe will fail and it knows to
restart the daemon).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import STATE_DIR


log = logging.getLogger("mixtape.daemon.bootstrap")


API_FILE_NAME = "api.json"
TOKEN_BYTES = 32  # 256-bit bearer token


def _api_path() -> Path:
    return STATE_DIR / API_FILE_NAME


@dataclass
class DaemonInfo:
    pid: int
    port: int
    token: str
    host: str = "127.0.0.1"
    started_at: float = 0.0
    version: str = "1"  # bump if wire shape changes

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def pick_free_port(host: str = "127.0.0.1") -> int:
    """Ask the kernel for an ephemeral port — same trick uvicorn uses."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def write_daemon_info(info: DaemonInfo) -> Path:
    p = _api_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(info), indent=2))
    tmp.replace(p)
    try:
        os.chmod(p, 0o600)  # bearer token — restrict to owner
    except OSError:
        pass
    log.info("daemon info written to %s (pid=%d port=%d)", p, info.pid, info.port)
    return p


def read_daemon_info() -> DaemonInfo | None:
    p = _api_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return DaemonInfo(
            pid=int(data["pid"]),
            port=int(data["port"]),
            token=str(data["token"]),
            host=str(data.get("host", "127.0.0.1")),
            started_at=float(data.get("started_at", 0.0)),
            version=str(data.get("version", "1")),
        )
    except (KeyError, ValueError, TypeError):
        return None


def clear_daemon_info() -> None:
    p = _api_path()
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def daemon_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def now_ts() -> float:
    return time.time()
