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
import shutil
import socket
import subprocess
import sys
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


def daemon_launch_argv() -> list[str]:
    """Build the argv used to start ``mixtape-daemon`` as a subprocess.

    Prefers ``pythonw.exe`` next to the current interpreter on Windows
    (Windows-subsystem PE — no console window). Falls back to the
    ``mixtape-daemon`` console script if it's on PATH, then to
    ``python -m mixtape.daemon.main``. Used by the desktop autostart
    shortcut and by the client when it auto-spawns the daemon."""
    if sys.platform == "win32":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            return [str(pythonw), "-m", "mixtape.daemon.main"]
    on_path = shutil.which("mixtape-daemon")
    if on_path:
        return [on_path]
    return [sys.executable, "-m", "mixtape.daemon.main"]


def detached_popen_kwargs() -> dict[str, object]:
    """Popen kwargs that fully detach a child from the calling console.

    Windows: ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`` —
    inherits no console, doesn't propagate Ctrl+C events.
    POSIX: ``start_new_session=True`` — new session, parent can exit
    without taking the child along."""
    kwargs: dict[str, object] = {"close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


def no_window_creationflags() -> int:
    """``CREATE_NO_WINDOW`` on Windows so a console-subsystem child
    spawned from a console-less parent (the tray daemon) doesn't pop
    its own terminal. ``0`` everywhere else."""
    if sys.platform == "win32":
        return int(subprocess.CREATE_NO_WINDOW)
    return 0
