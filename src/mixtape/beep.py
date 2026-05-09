"""Cross-platform PC-speaker / terminal beep.

Best-effort: tries the motherboard speaker first, falls back to BEL
(``\\x07``) on the controlling terminal. Stays silent (rather than
raising) if neither path works — a missing PC speaker on a headless
RPi should not break sync."""
from __future__ import annotations

import subprocess
import sys
import threading
import time


def _beep_once_windows(freq: int = 800, duration_ms: int = 150) -> None:
    try:
        import winsound
        winsound.Beep(freq, duration_ms)
    except Exception:
        pass


def _beep_once_posix(freq: int = 800, duration_ms: int = 150) -> None:
    # Try the `beep` command (drives the PC speaker via /dev/input/by-path/…).
    try:
        subprocess.run(
            ["beep", "-f", str(freq), "-l", str(duration_ms)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return
    except (FileNotFoundError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, OSError):
        pass
    # Fallback: write BEL to the controlling TTY. Terminals usually honour
    # this with their own bell sound or a visual flash.
    try:
        with open("/dev/tty", "w") as fp:
            fp.write("\a")
            fp.flush()
        return
    except OSError:
        pass
    try:
        sys.stderr.write("\a")
        sys.stderr.flush()
    except Exception:
        pass


def _beep_once() -> None:
    if sys.platform == "win32":
        _beep_once_windows()
    else:
        _beep_once_posix()


def beep(times: int = 1, *, gap_ms: int = 120) -> None:
    """Emit ``times`` short beeps in a background thread so callers don't
    block on the speaker (winsound.Beep is synchronous on Windows). Daemon
    thread — no need to wait for it."""
    def run() -> None:
        for i in range(times):
            if i > 0:
                time.sleep(gap_ms / 1000.0)
            _beep_once()
    threading.Thread(target=run, daemon=True, name=f"beep-x{times}").start()
