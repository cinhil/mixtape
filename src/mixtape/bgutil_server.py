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

from .config import STATE_DIR, bgutil_server_path

DEFAULT_PORT = 4416
SERVER_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
# yt-dlp's bgutil:http plugin queries 127.0.0.1, so we patch the server to
# bind there. We still ping [::1] as a fallback for unpatched/older installs
# where the server is IPv6-only on Windows (IPV6_V6ONLY default).
PING_URLS = (SERVER_URL, f"http://[::1]:{DEFAULT_PORT}")
PING_TIMEOUT = 1.0
# Cold-start on Windows is dominated by deno resolving the bgutil-server's
# transitive npm tree (jsdom + parse5 + w3c-xmlserializer + …). Measured at
# ~17 s on a stock Win11 box; warm starts are sub-second. 60 s leaves
# comfortable headroom for slower disks / antivirus scanning without
# delaying the user when the cache is already warm.
START_TIMEOUT = 60.0


def _find_deno() -> str | None:
    home = os.path.expanduser("~")
    candidates = [
        # Windows: Deno's installer drops deno.exe under %USERPROFILE%\.deno\bin
        os.path.join(home, ".deno", "bin", "deno.exe"),
        # POSIX layout
        os.path.join(home, ".deno", "bin", "deno"),
        # Anything on PATH (shutil.which honours PATHEXT on Windows so .exe is found)
        shutil.which("deno"),
        shutil.which("deno.exe"),
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
    for base in PING_URLS:
        try:
            with urllib.request.urlopen(f"{base}/ping", timeout=PING_TIMEOUT) as r:
                if 200 <= r.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            continue
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
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = STATE_DIR / "bgutil-server.log"

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
        popen_kwargs: dict = {
            "env": env, "cwd": str(server_dir),
            "stdin": subprocess.DEVNULL, "stdout": log_fp, "stderr": log_fp,
        }
        if os.name == "nt":
            # When mixtape runs from the tray (no console), spawning a
            # console-subsystem child like deno.exe with default flags
            # makes Windows pop a fresh terminal window. Suppress it.
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._proc = subprocess.Popen(cmd, **popen_kwargs)
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
