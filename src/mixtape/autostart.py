"""Cross-platform "start at login" helpers.

- **Windows**: writes a `.lnk` shortcut to the user's Startup folder
  (``%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup``). Picked
  up by the user session at login. No admin needed, easy to remove.
- **Linux**: writes an XDG autostart entry at
  ``~/.config/autostart/mixtape.desktop``. Honoured by GNOME, KDE, XFCE,
  Cinnamon… For headless RPi without a desktop session, prefer the
  ``mixtape.service`` systemd unit instead.

Both write the user's chosen *target command* — usually ``mixtape --tray``
so the app starts in the background as a system-tray icon.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


# ── Windows ────────────────────────────────────────────────────────────────

def _windows_startup_dir() -> Path:
    import os
    return (
        Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )


def _windows_shortcut_path() -> Path:
    return _windows_startup_dir() / "mixtape.lnk"


def _windows_enable(launcher_command: str) -> bool:
    """Create a .lnk shortcut launching ``launcher_command``.
    ``launcher_command`` should be a single executable path (e.g. ``mixtape``)
    or ``pwsh.exe`` with appropriate args."""
    try:
        # Use PowerShell's WScript.Shell to write the shortcut — no extra deps.
        ps_script = (
            f"$WshShell = New-Object -ComObject WScript.Shell;"
            f"$lnk = $WshShell.CreateShortcut('{_windows_shortcut_path()}');"
            f"$lnk.TargetPath = 'pwsh.exe';"
            f"$lnk.Arguments = '-WindowStyle Hidden -Command \"& mixtape --tray\"';"
            f"$lnk.WorkingDirectory = '{Path.home()}';"
            f"$lnk.Description = 'mixtape — background sync (tray)';"
            f"$lnk.Save();"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                        "-Command", ps_script], check=True, timeout=15)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _windows_disable() -> bool:
    p = _windows_shortcut_path()
    try:
        p.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _windows_is_enabled() -> bool:
    return _windows_shortcut_path().exists()


# ── Linux (XDG autostart) ──────────────────────────────────────────────────

def _linux_autostart_dir() -> Path:
    import os
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart"


def _linux_desktop_path() -> Path:
    return _linux_autostart_dir() / "mixtape.desktop"


def _linux_enable() -> bool:
    """Write a .desktop file that launches ``mixtape --tray`` at session start."""
    exe = shutil.which("mixtape") or "mixtape"
    body = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=mixtape\n"
        "Comment=Sync YouTube Music playlists to USB MP3 players\n"
        f"Exec={exe} --tray\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Audio;\n"
    )
    try:
        _linux_autostart_dir().mkdir(parents=True, exist_ok=True)
        _linux_desktop_path().write_text(body)
        return True
    except OSError:
        return False


def _linux_disable() -> bool:
    try:
        _linux_desktop_path().unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _linux_is_enabled() -> bool:
    return _linux_desktop_path().exists()


# ── Public API ─────────────────────────────────────────────────────────────

def is_supported() -> bool:
    """Whether autostart can be configured on this platform via this module."""
    return sys.platform == "win32" or sys.platform.startswith("linux")


def is_enabled() -> bool:
    if sys.platform == "win32":
        return _windows_is_enabled()
    if sys.platform.startswith("linux"):
        return _linux_is_enabled()
    return False


def enable() -> bool:
    if sys.platform == "win32":
        return _windows_enable("mixtape --tray")
    if sys.platform.startswith("linux"):
        return _linux_enable()
    return False


def disable() -> bool:
    if sys.platform == "win32":
        return _windows_disable()
    if sys.platform.startswith("linux"):
        return _linux_disable()
    return False
