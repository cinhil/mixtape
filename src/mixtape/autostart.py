"""Cross-platform "start at login" helpers.

- **Windows**: writes a `.lnk` shortcut to the user's Startup folder
  launching the mixtape daemon at logon. Picked up by the user session
  at login. No admin needed, easy to remove.
- **Linux**: writes an XDG autostart entry
  (``~/.config/autostart/mixtape-daemon.desktop``). Honoured by GNOME,
  KDE, XFCE, Cinnamon… For headless RPi without a desktop session,
  prefer the ``mixtape.service`` systemd unit instead.
- **macOS**: writes a LaunchAgent plist
  (``~/Library/LaunchAgents/com.cinhil.mixtape.plist``) and ``launchctl
  load``s it. Auto-starts the daemon at login.

The target is ``mixtape-daemon`` — the daemon-and-clients design
keeps a single long-running daemon; UI shells (TUI / desktop) connect
to it on demand.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


# ── Windows ────────────────────────────────────────────────────────────────

def _windows_startup_dir() -> Path:
    import os
    return (
        Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )


def _windows_shortcut_path() -> Path:
    return _windows_startup_dir() / "mixtape.lnk"


def _windows_enable() -> bool:
    """Create a .lnk shortcut that launches the daemon at user logon.
    Re-uses ``daemon_launch_argv`` so the executable + args match what
    the client uses when it auto-spawns the daemon — single source of
    truth for "how to start the daemon"."""
    from .daemon.bootstrap import daemon_launch_argv
    argv = daemon_launch_argv()
    target = argv[0]
    args = " ".join(argv[1:])
    try:
        ps_script = (
            f"$WshShell = New-Object -ComObject WScript.Shell;"
            f"$lnk = $WshShell.CreateShortcut('{_windows_shortcut_path()}');"
            f"$lnk.TargetPath = '{target}';"
            f"$lnk.Arguments = '{args}';"
            f"$lnk.WorkingDirectory = '{Path.home()}';"
            f"$lnk.WindowStyle = 7;"  # minimized — pythonw has no console anyway
            f"$lnk.Description = 'mixtape daemon (background sync engine)';"
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
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart"


def _linux_desktop_path() -> Path:
    return _linux_autostart_dir() / "mixtape-daemon.desktop"


def _linux_enable() -> bool:
    """Write an XDG autostart file that launches the daemon at session start."""
    exe = shutil.which("mixtape-daemon") or "mixtape-daemon"
    body = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=mixtape daemon\n"
        "Comment=mixtape background sync engine (daemon)\n"
        f"Exec={exe}\n"
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
        # Clean up the legacy mixtape.desktop too if it exists.
        legacy = _linux_autostart_dir() / "mixtape.desktop"
        legacy.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _linux_is_enabled() -> bool:
    return _linux_desktop_path().exists()


# ── macOS (LaunchAgent) ────────────────────────────────────────────────────

LAUNCH_AGENT_LABEL = "com.cinhil.mixtape.daemon"


def _macos_agent_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _macos_plist_path() -> Path:
    return _macos_agent_dir() / f"{LAUNCH_AGENT_LABEL}.plist"


def _macos_enable() -> bool:
    """Write a LaunchAgent plist + load it. RunAtLoad means the daemon
    starts automatically at login; KeepAlive=false means we don't fight
    the user if they `mixtape-daemon /shutdown` it manually."""
    exe = shutil.which("mixtape-daemon") or "mixtape-daemon"
    state_log = Path.home() / "Library" / "Logs" / "mixtape-daemon.log"
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f'  <key>Label</key><string>{LAUNCH_AGENT_LABEL}</string>\n'
        f'  <key>ProgramArguments</key><array><string>{exe}</string></array>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>KeepAlive</key><false/>\n'
        f'  <key>StandardOutPath</key><string>{state_log}</string>\n'
        f'  <key>StandardErrorPath</key><string>{state_log}</string>\n'
        '</dict></plist>\n'
    )
    try:
        _macos_agent_dir().mkdir(parents=True, exist_ok=True)
        state_log.parent.mkdir(parents=True, exist_ok=True)
        _macos_plist_path().write_text(plist)
        # `launchctl bootstrap gui/<uid>` is the modern verb; fall back
        # to legacy `launchctl load` if not present.
        uid = os.getuid()  # type: ignore[attr-defined]
        try:
            subprocess.run(
                ["launchctl", "bootstrap", f"gui/{uid}", str(_macos_plist_path())],
                check=True, timeout=10, capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            subprocess.run(
                ["launchctl", "load", "-w", str(_macos_plist_path())],
                check=False, timeout=10, capture_output=True,
            )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _macos_disable() -> bool:
    try:
        # Best-effort unload; ignore failures.
        try:
            uid = os.getuid()  # type: ignore[attr-defined]
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"],
                check=False, timeout=10, capture_output=True,
            )
        except FileNotFoundError:
            pass
        _macos_plist_path().unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _macos_is_enabled() -> bool:
    return _macos_plist_path().exists()


# ── Public API ─────────────────────────────────────────────────────────────

def _backend_for_platform() -> tuple[Callable[[], bool], Callable[[], bool], Callable[[], bool]] | None:
    """Return (enable, disable, is_enabled) for the current OS, or None."""
    if sys.platform == "win32":
        return (_windows_enable, _windows_disable, _windows_is_enabled)
    if sys.platform == "darwin":
        return (_macos_enable, _macos_disable, _macos_is_enabled)
    if sys.platform.startswith("linux"):
        return (_linux_enable, _linux_disable, _linux_is_enabled)
    return None


def is_supported() -> bool:
    """Whether autostart can be configured on this platform via this module."""
    return _backend_for_platform() is not None


def enable() -> bool:
    backend = _backend_for_platform()
    return backend[0]() if backend else False


def disable() -> bool:
    backend = _backend_for_platform()
    return backend[1]() if backend else False


def is_enabled() -> bool:
    backend = _backend_for_platform()
    return backend[2]() if backend else False
