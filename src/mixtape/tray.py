"""System tray app — runs the headless USB watcher behind a tray icon.

Cross-platform via ``pystray``. A quick visual recap:

- 🟩 idle / cookies valid
- 🟨 syncing / cookies expired
- 🟥 startup failure (no deno, no bgutil, …)

Menu (right-click):
- Open TUI       — spawn a new terminal with the interactive TUI
- Sync all now   — kick a manual sync of the active library
- Pause auto-sync— ignore USB plug events until un-paused
- Show last log  — reveal the sync log file in the OS file browser
- Quit           — stop the daemon and remove the icon

If pystray can't initialise (e.g. headless RPi without a desktop), the
caller should fall back to the CLI ``--headless`` mode.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Literal


log = logging.getLogger("mixtape.tray")


_State = Literal["idle", "syncing", "warning", "error"]


# ── PID file for the running tray daemon ────────────────────────────────────
# A second tray instance would fight the first for port 4416 and the USB
# watcher; the PID file lets settings tell whether one is already running and
# lets the user toggle it off cleanly.

def _pid_file_path() -> Path:
    from .config import STATE_DIR
    return STATE_DIR / "tray.pid"


def _pid_alive(pid: int) -> bool:
    """Best-effort cross-platform 'is this PID still alive' check."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it (rare on Windows for our own
        # spawned children, but treat as "alive" — better than killing user
        # workflow with a false negative).
        return True
    except OSError:
        return False
    return True


def tray_is_running() -> bool:
    p = _pid_file_path()
    if not p.is_file():
        return False
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return False
    if _pid_alive(pid):
        return True
    # Stale file — remove it so subsequent checks don't keep returning False
    # via the parse path.
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
    return False


def kill_running_tray(timeout: float = 5.0) -> tuple[bool, str]:
    """Stop the running tray daemon by signalling its PID. Returns
    (ok, message)."""
    import time
    p = _pid_file_path()
    if not p.is_file():
        return False, "tray is not running (no pid file)"
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError) as e:
        return False, f"unreadable pid file: {e}"
    # Safety net: if PID reuse landed our own process number in the file
    # (e.g. tray crashed before writing, then OS recycled the PID into our
    # current TUI), refuse to SIGTERM ourselves.
    if pid == os.getpid():
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
        return False, "pid file points at this process — refusing to self-kill"
    if not _pid_alive(pid):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
        return False, "tray was not running (stale pid)"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        return False, f"could not signal pid {pid}: {e}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
            return True, f"tray (pid {pid}) stopped"
        time.sleep(0.1)
    return False, f"tray (pid {pid}) did not exit within {timeout:.0f}s"


_STATE_DOT = {
    "idle":    (76, 175, 80, 255),    # green
    "syncing": (33, 150, 243, 255),   # blue
    "warning": (255, 193, 7, 255),    # amber
    "error":   (244, 67, 54, 255),    # red
}


def _make_icon_image(state: _State):
    """Return a PIL Image for the tray icon: the mixtape cassette logo with a
    small status-colour dot in the corner."""
    from pathlib import Path
    from PIL import Image, ImageDraw

    # Find the bundled mixtape.png (project root, two levels up from this file).
    candidates = [
        Path(__file__).resolve().parents[2] / "mixtape.png",
        Path(__file__).resolve().parents[1] / "mixtape.png",
    ]
    base: Image.Image | None = None
    for p in candidates:
        if p.is_file():
            try:
                base = Image.open(p).convert("RGBA")
                break
            except Exception:  # noqa: BLE001
                continue

    if base is None:
        # Fallback: the old simple coloured circle if the asset is missing.
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), fill=_STATE_DOT.get(state, (158, 158, 158, 255)),
                  outline=(0, 0, 0, 255), width=2)
        return img

    # Standardise to a manageable square (most platforms render 64-or-so).
    icon = base.resize((128, 128), Image.LANCZOS)

    # Overlay a small status dot (lower-right ~25% of the size).
    d = ImageDraw.Draw(icon)
    dot_color = _STATE_DOT.get(state, (158, 158, 158, 255))
    dot_box = (78, 78, 122, 122)
    d.ellipse(dot_box, fill=dot_color, outline=(20, 20, 20, 255), width=3)
    return icon


class TrayApp:
    """Tray icon + headless USB watcher + bgutil daemon, all in one process."""

    def __init__(self) -> None:
        from .config import Config
        from .bgutil_server import BgutilServer
        self.cfg = Config.load()
        self.bgutil = BgutilServer()
        self._stop = threading.Event()
        self.paused = False
        self.state: _State = "idle"
        self._icon = None  # pystray.Icon — assigned in start()
        self._sync_lock = threading.Lock()
        self._watcher = None  # platform_io.VolumeWatcher

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> int:
        """Build the tray icon and run the event loop. Blocks until Quit."""
        if tray_is_running():
            log.error("another mixtape tray is already running — refusing to start a second one.")
            return 1

        # Claim the PID file FIRST so the settings screen's polling loop
        # detects us within a few hundred ms — pystray import + bgutil
        # bring-up can take a couple of seconds and that delay used to make
        # the settings UI report "tray didn't come up within 5s" while the
        # icon was actually about to appear.
        pid_path = _pid_file_path()
        try:
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(os.getpid()))
        except OSError as e:
            log.warning("could not write tray pid file: %s", e)

        try:
            import pystray
        except ImportError:
            log.error("pystray not installed — tray mode unavailable.")
            try:
                pid_path.unlink(missing_ok=True)
            except OSError:
                pass
            return 2

        # Headless background bits
        ok, msg = self.bgutil.start()
        log.info("bgutil: %s — %s", "ok" if ok else "fail", msg)
        if not ok:
            self.state = "warning"

        from .platform_io import VolumeWatcher
        self._watcher = VolumeWatcher(self._on_volume_change)
        self._watcher.start()

        menu = pystray.Menu(
            pystray.MenuItem("Open TUI", self._open_tui, default=True),
            pystray.MenuItem("Sync all now", self._sync_all_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause auto-sync", self._toggle_pause,
                checked=lambda _i: self.paused,
            ),
            pystray.MenuItem("Show last sync log", self._open_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit mixtape", self._quit),
        )
        self._icon = pystray.Icon(
            "mixtape", _make_icon_image(self.state), title="mixtape", menu=menu,
        )
        try:
            self._icon.run()  # blocks
        finally:
            self._cleanup()
        return 0

    def _cleanup(self) -> None:
        self._stop.set()
        if self._watcher:
            try:
                self._watcher.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.bgutil.stop()
        except Exception:  # noqa: BLE001
            pass
        # Release the PID file so settings stops thinking we're running.
        try:
            _pid_file_path().unlink(missing_ok=True)
        except OSError:
            pass

    # ── menu actions ───────────────────────────────────────────────────────

    def _open_tui(self, _icon=None, _item=None) -> None:
        """Launch a new terminal running the interactive TUI."""
        cmd = self._spawn_tui_command()
        if cmd is None:
            self._notify("Couldn't find a terminal to launch the TUI.")
            return
        try:
            subprocess.Popen(cmd, start_new_session=True)
        except OSError as e:
            self._notify(f"Could not launch TUI: {e}")

    def _spawn_tui_command(self) -> list[str] | None:
        if sys.platform == "win32":
            # Open a new pwsh window; mixtape inside it is the TUI mode
            for exe in ("wt.exe", "pwsh.exe", "powershell.exe"):
                p = shutil.which(exe)
                if p:
                    if exe == "wt.exe":
                        return [p, "pwsh.exe", "-NoExit", "-Command", "mixtape"]
                    return [p, "-NoExit", "-Command", "mixtape"]
            return None
        # Linux: try a terminal emulator in priority order
        for emu in ("x-terminal-emulator", "gnome-terminal", "konsole",
                    "xfce4-terminal", "alacritty", "kitty", "xterm"):
            p = shutil.which(emu)
            if not p:
                continue
            mixtape_exe = shutil.which("mixtape") or "mixtape"
            if emu == "gnome-terminal":
                return [p, "--", mixtape_exe]
            return [p, "-e", mixtape_exe]
        return None

    def _sync_all_now(self, _icon=None, _item=None) -> None:
        if self.paused:
            self._notify("Auto-sync is paused — un-pause first.")
            return
        threading.Thread(target=self._do_sync_all, daemon=True, name="tray-sync").start()

    def _do_sync_all(self) -> None:
        if not self._sync_lock.acquire(blocking=False):
            self._notify("A sync is already running.")
            return
        try:
            from .beep import beep
            beep(1)  # single beep: sync starting
            self._set_state("syncing")
            self._notify("Sync started…")
            from .config import Config
            from .downloader import sync_playlist
            from .platform_io import flush_filesystem
            self.cfg = Config.load()
            lib = self.cfg.active_library_obj()
            playlists = self.cfg.active_playlists()
            for i, pl in enumerate(playlists):
                try:
                    sync_playlist(pl, lib, i, lambda ev: None)
                except Exception as e:  # noqa: BLE001
                    log.error("playlist %r failed: %s", pl.name, e)
            try:
                flush_filesystem()
            except Exception:
                pass
            beep(2)  # double beep: sync finished — safe to unplug
            self._set_state("idle")
            self._notify(f"Sync done — '{lib.name}' is safe to unplug.")
        finally:
            self._sync_lock.release()

    def _toggle_pause(self, _icon=None, _item=None) -> None:
        self.paused = not self.paused
        self._notify("Auto-sync paused." if self.paused else "Auto-sync resumed.")

    def _open_log(self, _icon=None, _item=None) -> None:
        log_path = Path(self.cfg.active_library_obj().path).expanduser() / "sync.log"
        if not log_path.exists():
            self._notify("No sync log yet (run a sync first).")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(log_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])
        except OSError as e:
            self._notify(f"Couldn't open log: {e}")

    def _quit(self, _icon=None, _item=None) -> None:
        if self._icon:
            self._icon.stop()

    # ── USB watcher hook ───────────────────────────────────────────────────

    def _on_volume_change(self, change) -> None:
        if self.paused:
            return
        # Reuse the headless logic for "is this our device → switch + sync".
        from .config import Config
        from .library_marker import find_marker_on_volume
        self.cfg = Config.load()
        for vol in change.added:
            marker_hit = find_marker_on_volume(Path(str(vol.mount_path)))
            if not marker_hit:
                continue
            marker, marker_root = marker_hit
            lib = self.cfg.get_library_by_uuid(marker.uuid)
            if not lib or not lib.auto_sync:
                continue
            self.cfg.set_active_library(lib.name)
            self._do_sync_all()  # already locked + threaded internally? no —
            # _do_sync_all here is synchronous but called from watcher thread.
            # Acceptable: the watcher thread blocks during sync; new plug events
            # are queued by the OS and re-emitted on next poll.

    # ── helpers ────────────────────────────────────────────────────────────

    def _set_state(self, state: _State) -> None:
        self.state = state
        if self._icon:
            try:
                self._icon.icon = _make_icon_image(state)
            except Exception:  # noqa: BLE001
                pass

    def _notify(self, message: str) -> None:
        if self._icon and getattr(self._icon, "HAS_NOTIFICATION", False):
            try:
                self._icon.notify(message, "mixtape")
                return
            except Exception:  # noqa: BLE001
                pass
        log.info("notify: %s", message)


def spawn_detached() -> tuple[bool, str]:
    """Launch ``mixtape --tray`` as a detached subprocess and return
    (ok, message). Used by the settings "Tray running" toggle and by the
    TUI's close-to-tray quit path.

    The child must NOT share the TUI's console: when it does, every
    Textual input event the parent processes can deliver a console
    control event (e.g. CTRL_C_EVENT) to the child too — we observed
    the tray dying with KeyboardInterrupt mid-`subprocess.run()` while
    enumerating volumes the moment a Switch in the TUI fired. On
    Windows we therefore set ``DETACHED_PROCESS`` (no inherited console
    at all) plus ``CREATE_NEW_PROCESS_GROUP``. On POSIX
    ``start_new_session=True`` already gives us a fresh session.

    Tray stdout/stderr go to ``STATE_DIR/tray-spawn.log`` so failures
    (pystray init, missing OLE, etc.) leave a tail-able trail."""
    from .config import STATE_DIR
    # On Windows, prefer pythonw.exe (Windows subsystem — no console
    # window ever) over mixtape.exe (console launcher — Windows allocates
    # a console for it, which appears as a stray terminal *and* ties the
    # tray's lifetime to that window). Fall back gracefully.
    if sys.platform == "win32":
        from pathlib import Path
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            cmd = [str(pythonw), "-m", "mixtape", "--tray"]
        else:
            exe = shutil.which("mixtape") or sys.executable
            cmd = [exe, "-m", "mixtape", "--tray"] if not exe.endswith(("mixtape", "mixtape.exe")) else [exe, "--tray"]
    else:
        exe = shutil.which("mixtape") or sys.executable
        cmd = [exe, "-m", "mixtape", "--tray"] if not exe.endswith(("mixtape", "mixtape.exe")) else [exe, "--tray"]
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "tray-spawn.log"
        log_fp = log_path.open("a", encoding="utf-8")
        log_fp.write(f"\n--- spawn {os.getpid()} → {' '.join(cmd)} ---\n")
        log_fp.flush()
        popen_kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_fp,
            "stderr": log_fp,
        }
        if sys.platform == "win32":
            # DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200.
            # Use the named subprocess constants so future Python upgrades that
            # add new bits don't drift out from under us.
            popen_kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            # `close_fds=False` lets the inheritable log_fp pass through; on
            # Windows that's the default but be explicit so the contract is
            # obvious to a future reader.
            popen_kwargs["close_fds"] = False
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **popen_kwargs)
        return True, f"tray launched (log: {log_path})"
    except OSError as e:
        return False, str(e)


def run_tray() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return TrayApp().start()
