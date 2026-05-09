from __future__ import annotations

import threading
from pathlib import Path

from textual.app import App

from .bgutil_server import BgutilServer
from .config import Config
from .cookies_check import CookieStatus, get_cookie_status, invalidate_cache as invalidate_cookie_cache
from .library_marker import find_marker_on_volume
from .platform_io import VolumeChange, VolumeWatcher, platform_name, reconcile_library_path
from .screens.playlists import PlaylistsScreen
from .screens.sync import SyncScreen
from .update_check import UpdateStatus, get_update_status


class MixtapeApp(App):
    """A small Textual app to manage and sync YouTube Music playlists."""

    CSS = """
    Screen { background: $background; }
    """

    TITLE = "mixtape (beta)"

    def __init__(self) -> None:
        super().__init__()
        self.config = Config.load()
        self.bgutil = BgutilServer()
        self.bgutil_status: tuple[str, str] = ("pending", "")
        self.cookie_status: CookieStatus = CookieStatus(state="unknown", message="checking…")
        self.update_status: UpdateStatus | None = None
        self.usb = VolumeWatcher(self._on_volume_change)
        self.platform = platform_name()

    def on_mount(self) -> None:
        ok, msg = self.bgutil.start()
        self.bgutil_status = ("ok" if ok else "fail", msg)
        threading.Thread(target=self._refresh_cookie_status, daemon=True, name="cookie-check").start()
        threading.Thread(target=self._refresh_update_status, daemon=True, name="update-check").start()
        self.usb.start()
        self.push_screen(PlaylistsScreen(self.config))

    def on_unmount(self) -> None:
        self.usb.stop()
        self.bgutil.stop()

    # --- USB device handling ---

    def _on_volume_change(self, change: VolumeChange) -> None:
        for vol in change.added:
            # 1) Strongest signal: a .mixtape marker on the volume.
            marker_hit = find_marker_on_volume(Path(str(vol.mount_path)))
            if marker_hit:
                marker, marker_root = marker_hit
                lib = self.config.get_library_by_uuid(marker.uuid)
                if lib:
                    new_path = str(marker_root)
                    self.call_from_thread(
                        self._on_known_device_plugged, lib.name, vol.identifier, new_path,
                    )
                    continue
                # Marker exists but library isn't registered on this machine yet.
                self.call_from_thread(
                    self._notify_marker_found, marker.name, vol.identifier, str(marker_root),
                )
                continue
            # 2) Fallback: legacy match by volume label (no marker yet)
            matching = next(
                (lib for lib in self.config.libraries
                 if lib.volume_name and lib.volume_name == vol.label),
                None,
            )
            if matching:
                new_path = reconcile_library_path(matching.path, vol)
                self.call_from_thread(
                    self._on_known_device_plugged, matching.name, vol.identifier, new_path,
                )
            else:
                self.call_from_thread(
                    self._notify_unknown_device, vol.label or vol.identifier, vol.identifier,
                )
        if change.removed:
            # We don't track which volume identifier was tied to which library,
            # so we don't need the identifiers here — _on_volume_removed checks
            # the active library's `online` property to decide whether the
            # disappearance affects us.
            self.call_from_thread(self._on_volume_removed)

    def _on_known_device_plugged(self, library_name: str, identifier: str, new_path: str) -> None:
        lib = self.config.get_library(library_name)
        path_changed = lib is not None and lib.path != new_path
        if path_changed and lib is not None:
            lib.path = new_path
            self.config.save()
        suffix = f" (path moved → {new_path})" if path_changed else ""
        self.notify(
            f"📀 Device '{library_name}' ({identifier}) detected — switching active library.{suffix}",
            severity="information", timeout=8,
        )
        self.config.set_active_library(library_name)
        # Refresh PlaylistsScreen if visible
        for s in self.screen_stack:
            if isinstance(s, PlaylistsScreen):
                s.config = self.config
                try:
                    s._refresh_table()
                    s._refresh_status()
                except Exception:
                    pass
        # Auto-sync if the library opted in and cookies are valid
        lib = self.config.get_library(library_name)
        playlists = self.config.active_playlists()
        if lib and lib.auto_sync and self.cookie_status.ok and playlists:
            self.notify("Auto-syncing all playlists to this device…", severity="information")
            for s in self.screen_stack:
                if isinstance(s, PlaylistsScreen):
                    s.action_sync_all()
                    break

    def _on_volume_removed(self) -> None:
        """A removable volume disappeared. If it was the active library,
        cancel any in-flight sync, switch to a still-online library, and
        repaint whatever screen is currently displayed."""
        active = self.config.active_library_obj()
        if active.online:
            return  # active library still accessible — nothing to do
        # Cancel + close any open SyncScreen for the (now-gone) device.
        for screen in list(self.screen_stack):
            if isinstance(screen, SyncScreen):
                screen.force_close()
                break
        # Pick a fallback: prefer libraries that are online; if none are,
        # keep whatever the first library is (so the app stays usable
        # offline) — that's typically the local "PC" entry.
        fallback = next(
            (lib for lib in self.config.libraries if lib.online and lib.name != active.name),
            None,
        )
        if fallback is None and self.config.libraries:
            fallback = self.config.libraries[0]
        if fallback and fallback.name != self.config.active_library:
            self.config.set_active_library(fallback.name)
            self.config.save()
            self.notify(
                f"📤 '{active.name}' unplugged — switched to '{fallback.name}'.",
                severity="warning", timeout=8,
            )
        else:
            self.notify(
                f"📤 '{active.name}' unplugged.",
                severity="warning", timeout=6,
            )
        # Refresh whatever screens expose a `_refresh_status` / `_refresh_table`.
        for screen in self.screen_stack:
            for fn in ("_refresh_table", "_refresh_status"):
                refresh = getattr(screen, fn, None)
                if callable(refresh):
                    try:
                        refresh()
                    except Exception:
                        pass

    def _notify_unknown_device(self, label: str, identifier: str) -> None:
        self.notify(
            f"🔌 New drive detected: {identifier} ('{label}'). Press 'l' → 'u' to register it as a library.",
            severity="information", timeout=10,
        )

    def _notify_marker_found(self, marker_name: str, identifier: str, root: str) -> None:
        self.notify(
            f"📀 Found mixtape library '{marker_name}' on {identifier} (at {root}). "
            f"Press 'l' → 'u' to register it on this machine — the device's UUID will be reused.",
            severity="information", timeout=12,
        )

    # --- Cookie status ---

    def _refresh_cookie_status(self, force: bool = False) -> None:
        if force:
            invalidate_cookie_cache()
        status = get_cookie_status(force=force)
        self.call_from_thread(self._on_cookie_status, status)

    def _on_cookie_status(self, status: CookieStatus) -> None:
        self.cookie_status = status
        for s in self.screen_stack:
            if isinstance(s, PlaylistsScreen):
                try:
                    s._refresh_status()
                except Exception:
                    pass

    def recheck_cookies(self) -> None:
        """Public hook — call after the user pastes new cookies."""
        # Immediately reflect "checking" in the status bar so the user gets
        # feedback while the network call (~1-3s) is in flight. The thread
        # below will overwrite it with the real result.
        self.cookie_status = CookieStatus(state="unknown", message="checking…")
        self._on_cookie_status(self.cookie_status)
        threading.Thread(
            target=self._refresh_cookie_status,
            args=(True,), daemon=True, name="cookie-recheck",
        ).start()

    # --- Update status ---

    def _refresh_update_status(self) -> None:
        status = get_update_status()
        self.call_from_thread(self._on_update_status, status)

    def _on_update_status(self, status: UpdateStatus | None) -> None:
        self.update_status = status
        for s in self.screen_stack:
            if isinstance(s, PlaylistsScreen):
                try:
                    s._refresh_status()
                except Exception:
                    pass


def main() -> None:
    import sys
    if "--set-cookies" in sys.argv:
        from .cli import set_cookies_from_stdin
        sys.exit(set_cookies_from_stdin())
    if "--headless" in sys.argv or "-H" in sys.argv:
        from .headless import run_headless
        sys.exit(run_headless())
    if "--tray" in sys.argv or "-T" in sys.argv:
        from .tray import run_tray
        sys.exit(run_tray())
    app = MixtapeApp()
    try:
        app.run()
    finally:
        # Defensive: stop daemon even if Textual exits abnormally.
        app.bgutil.stop()


if __name__ == "__main__":
    main()
