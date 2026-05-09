"""Cross-platform USB volume detection.

Backends:
- WSL2 (Windows drives via PowerShell ``Get-Volume``)
- Linux native (udisks2 auto-mounts to ``/run/media/<user>/`` or ``/media/<user>/``)
- Windows native (WMI via ``Get-Volume`` again — same code path as WSL)

Detection is automatic at runtime via :func:`detect_backend`.
The public interface is identical across backends, so callers don't care.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

POLL_INTERVAL_SEC = 5.0


@dataclass
class Volume:
    identifier: str  # platform-specific stable id (drive letter / device node)
    label: str  # human-readable volume label (FAT32 LABEL, ntfs label, …)
    mount_path: Path  # accessible filesystem path (where files live)
    fs_type: str  # "FAT32", "NTFS", "ext4", …
    size_bytes: int = 0
    free_bytes: int = 0
    is_removable: bool = False


@dataclass
class VolumeChange:
    added: list[Volume]
    removed: list[str]  # identifiers


VolumeCallback = Callable[[VolumeChange], None]


# ── Platform detection ───────────────────────────────────────────────────────

def is_wsl() -> bool:
    if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def is_windows() -> bool:
    return sys.platform == "win32"


def is_linux() -> bool:
    return sys.platform.startswith("linux") and not is_wsl()


def platform_name() -> str:
    if is_wsl():
        return "wsl"
    if is_windows():
        return "windows"
    if is_linux():
        return "linux"
    return sys.platform


# ── Backend interface ────────────────────────────────────────────────────────

class _Backend:
    """Concrete subclasses implement list_volumes(). Watching is generic
    polling on top of that — backends only need to override list_volumes()."""

    def list_volumes(self) -> list[Volume]:  # noqa: D401
        return []


# ── WSL backend (PowerShell Get-Volume) ──────────────────────────────────────

class _WSLBackend(_Backend):
    def list_volumes(self) -> list[Volume]:
        return _list_volumes_powershell()


# ── Windows native backend (same PowerShell call, different mount paths) ────

class _WindowsBackend(_Backend):
    def list_volumes(self) -> list[Volume]:
        # Same Get-Volume but mount paths are "D:\" not "/mnt/d"
        return _list_volumes_powershell(wsl_paths=False)


# ── Linux backend (udisks2-mounted USB drives) ───────────────────────────────

class _LinuxBackend(_Backend):
    def list_volumes(self) -> list[Volume]:
        return _list_volumes_linux()


def detect_backend() -> _Backend:
    if is_wsl():
        return _WSLBackend()
    if is_windows():
        return _WindowsBackend()
    if is_linux():
        return _LinuxBackend()
    return _Backend()


# ── Implementations ──────────────────────────────────────────────────────────

def _list_volumes_powershell(*, wsl_paths: bool = True) -> list[Volume]:
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "Get-Volume | Where-Object { $_.DriveLetter } | "
        "Select-Object DriveLetter, FileSystemLabel, DriveType, FileSystemType, Size, SizeRemaining "
        "| ConvertTo-Json -Compress",
    ]
    run_kwargs: dict = {
        "capture_output": True, "timeout": 10, "text": True, "check": True,
    }
    if os.name == "nt":
        # Without this, the console-less tray process makes Windows pop a
        # fresh terminal window every poll (~5s).
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, **run_kwargs)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    out = (result.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    volumes: list[Volume] = []
    for v in data:
        letter = v.get("DriveLetter")
        if not letter:
            continue
        letter = str(letter)
        drive_type = str(v.get("DriveType") or "")
        mount = Path(f"/mnt/{letter.lower()}") if wsl_paths else Path(f"{letter}:\\")
        volumes.append(Volume(
            identifier=letter,
            label=str(v.get("FileSystemLabel") or ""),
            mount_path=mount,
            fs_type=str(v.get("FileSystemType") or ""),
            size_bytes=int(v.get("Size") or 0),
            free_bytes=int(v.get("SizeRemaining") or 0),
            is_removable=(drive_type == "Removable"),
        ))
    return volumes


def _list_volumes_linux() -> list[Volume]:
    """Find user-accessible mounts under standard udisks2 dirs."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    candidate_roots = [Path("/run/media") / user, Path("/media") / user, Path("/media")]
    seen: set[str] = set()
    volumes: list[Volume] = []
    for root in candidate_roots:
        if not root.is_dir():
            continue
        try:
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                if str(entry) in seen:
                    continue
                seen.add(str(entry))
                stat = _safe_stat(entry)
                fs_type = _detect_fs_type(entry)
                volumes.append(Volume(
                    identifier=str(entry),
                    label=entry.name,
                    mount_path=entry,
                    fs_type=fs_type,
                    size_bytes=stat[0],
                    free_bytes=stat[1],
                    is_removable=True,  # under /media is a strong signal
                ))
        except OSError:
            continue
    return volumes


def _safe_stat(path: Path) -> tuple[int, int]:
    try:
        st = os.statvfs(path)
        return st.f_frsize * st.f_blocks, st.f_frsize * st.f_bavail
    except OSError:
        return 0, 0


def _detect_fs_type(path: Path) -> str:
    # Cheap: parse /proc/mounts for the mountpoint
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == str(path):
                    return parts[2]
    except OSError:
        pass
    return ""


# ── Watcher (polling, generic on top of list_volumes) ────────────────────────

class VolumeWatcher:
    """Background thread that polls the backend and emits VolumeChange events."""

    def __init__(self, on_change: VolumeCallback, backend: _Backend | None = None) -> None:
        self.backend = backend or detect_backend()
        self.on_change = on_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._known: dict[str, Volume] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Seed with current state so the first tick doesn't re-announce existing drives
        self._known = {v.identifier: v for v in self._safe_list()}
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="volume-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _safe_list(self) -> list[Volume]:
        try:
            return self.backend.list_volumes()
        except Exception:  # noqa: BLE001
            return []

    def _loop(self) -> None:
        while not self._stop.is_set():
            current = {v.identifier: v for v in self._safe_list()}
            added = [v for ident, v in current.items() if ident not in self._known]
            removed = [ident for ident in self._known if ident not in current]
            if added or removed:
                try:
                    self.on_change(VolumeChange(added=added, removed=removed))
                except Exception:  # noqa: BLE001
                    pass
            self._known = current
            self._stop.wait(POLL_INTERVAL_SEC)


# ── Filesystem flush ─────────────────────────────────────────────────────────

def reconcile_library_path(old_path: str, current_volume: Volume) -> str:
    """When a registered USB device is re-plugged, its drive letter (or
    ``/dev/sdX`` node) may change. We match it by its (stable) volume label,
    then have to rewrite the library's stored path to wherever it lives now.

    Preserves any sub-folder the user originally selected (e.g. an old path of
    ``/mnt/d/music`` becomes ``/mnt/e/music`` if the device is now at E:)."""
    old = Path(old_path)
    new_root = Path(str(current_volume.mount_path))
    for candidate in (Path("/mnt"), Path("/media"), Path("/run/media")):
        try:
            rest = old.relative_to(candidate)
            parts = rest.parts
            # parts[0] is the drive-letter / username component — drop it.
            sub = Path(*parts[1:]) if len(parts) > 1 else Path()
            return str(new_root / sub)
        except ValueError:
            continue
    # Fallback for Windows-native paths like "D:\music":
    if len(old.parts) >= 1 and len(old.parts[0]) <= 3 and ":" in old.parts[0]:
        return str(new_root.joinpath(*old.parts[1:]))
    return str(new_root)


def flush_filesystem(path: Path | None = None) -> None:
    """Force OS-level sync so files written to a removable drive are physically
    on disk and the device can be unplugged safely.

    On Linux/macOS: ``os.sync()`` flushes all kernel buffers (system-wide, but
    that's fine — it's cheap relative to the audio download we just did).
    On Windows: no direct equivalent in os.*, fall back to syncing each file
    we know about via FlushFileBuffers — but for simplicity we just rely on
    Python having closed file handles + a short wait.
    """
    if hasattr(os, "sync"):
        try:
            os.sync()  # type: ignore[attr-defined]
        except OSError:
            pass
