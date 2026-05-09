"""Manage a long-running bgutil PO Token server (Deno + Express on :4416).

The server keeps a single SessionManager / BotGuard integrity token alive in
memory and reuses it across video requests. This avoids the rate-limiting that
plagues the per-request "script mode" when downloading many tracks in a row.

yt-dlp's bgutil:http provider auto-discovers the server at 127.0.0.1:4416, so
once the daemon is up there's nothing else to wire up — yt-dlp just uses it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import bgutil_server_path

DEFAULT_PORT = 4416
SERVER_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
PING_TIMEOUT = 1.0
START_TIMEOUT = 15.0


def _find_deno() -> str | None:
    candidates = [
        os.path.expanduser("~/.deno/bin/deno"),
        shutil.which("deno"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            subprocess.run(
                [path, "--version"],
                check=True, capture_output=True, timeout=5, text=True,
            )
            return path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
    return None


def is_server_running() -> bool:
    """Quick health check on the bgutil HTTP endpoint."""
    try:
        with urllib.request.urlopen(f"{SERVER_URL}/ping", timeout=PING_TIMEOUT) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


class BgutilServer:
    """Spawn the bgutil HTTP server as a daemon, tied to the lifetime of one
    process. Idempotent: if a server is already running on :4416 (e.g. from
    a previous app instance), we just use it and don't spawn ours."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log_path: Path | None = None
        self._owned = False  # True if we spawned this server (and should kill it)

    @property
    def url(self) -> str:
        return SERVER_URL

    def start(self) -> tuple[bool, str]:
        """Start the server (idempotent). Returns (ok, message)."""
        server_dir = bgutil_server_path()
        if not server_dir:
            return False, "bgutil-server not installed (run ./setup-bgutil.sh)"
        if is_server_running():
            return True, "already running (reused)"
        deno = _find_deno()
        if not deno:
            return False, "deno not found in PATH"

        node_modules = server_dir / "node_modules"
        cache_dir = Path.home() / ".cache" / "bgutil-ytdlp-pot-provider"
        cache_dir.mkdir(parents=True, exist_ok=True)
        log_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "mixtape"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / "bgutil-server.log"

        env = {
            **os.environ,
            "DENO_NO_PROMPT": "1",
            "DENO_NO_UPDATE_CHECK": "1",
            "FORCE_COLOR": "false",
        }
        cmd = [
            deno, "run",
            "--allow-env", "--allow-net",
            f"--allow-ffi={node_modules}",
            f"--allow-write={cache_dir}",
            f"--allow-read={cache_dir},{node_modules}",
            str(server_dir / "src" / "main.ts"),
        ]
        log_fp = self._log_path.open("a", encoding="utf-8")
        log_fp.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_fp.flush()
        try:
            self._proc = subprocess.Popen(
                cmd, env=env, cwd=str(server_dir),
                stdin=subprocess.DEVNULL, stdout=log_fp, stderr=log_fp,
            )
        except OSError as e:
            return False, f"could not start daemon: {e}"
        self._owned = True

        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                return False, f"daemon exited early (see {self._log_path})"
            if is_server_running():
                return True, f"started (PID {self._proc.pid})"
            time.sleep(0.2)
        # Timeout
        self.stop()
        return False, f"daemon didn't respond within {START_TIMEOUT:.0f}s"

    def stop(self) -> None:
        if not self._owned or not self._proc:
            return
        if self._proc.poll() is not None:
            self._proc = None
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass
        self._proc = None
