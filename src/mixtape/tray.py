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
import subprocess
import sys
import threading
from pathlib import Path
from typing import Literal


log = logging.getLogger("mixtape.tray")


_State = Literal["idle", "syncing", "warning", "error"]


def _make_icon_image(state: _State):
    """Return a PIL Image used as the tray icon."""
    from PIL import Image, ImageDraw
    color = {
        "idle":    (76, 175, 80, 255),    # green
        "syncing": (33, 150, 243, 255),   # blue
        "warning": (255, 193, 7, 255),    # amber
        "error":   (244, 67, 54, 255),    # red
    }.get(state, (158, 158, 158, 255))
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color, outline=(0, 0, 0, 255), width=2)
    # Letter "M"
    d.text((20, 16), "M", fill=(255, 255, 255, 255))
    return img


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
        try:
            import pystray
        except ImportError:
            log.error("pystray not installed — tray mode unavailable.")
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


def run_tray() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return TrayApp().start()
