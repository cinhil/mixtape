from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

import shutil

from ..config import Config, _slugify, bgutil_server_path
from .add_playlist import AddPlaylistScreen
from .confirm_delete import ConfirmDeleteScreen, DeleteResult
from .cookies import CookiesScreen
from .import_library import ImportLibraryScreen
from .libraries import LibrariesScreen
from .quitting import QuittingScreen
from .settings import SettingsScreen
from .sync import SyncScreen
from .update import UpdateScreen


class PlaylistsScreen(Screen):
    """Main screen — table of configured playlists."""

    CSS = """
    Screen { background: $background; }
    #status-bar { height: 1; padding: 0 1; color: $text-muted; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("s", "sync_one", "Sync sel."),
        Binding("S", "sync_all", "Sync all"),
        Binding("c", "cookies", "Cookies"),
        Binding("i", "import_lib", "Import"),
        Binding("l", "libraries", "Libraries"),
        Binding("o", "settings", "Settings"),
        Binding("u", "update", "Update"),
        Binding("q", "quit_app", "Quit", priority=True),
        Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
    ]

    def action_quit_app(self) -> None:
        # Signal cancel to any sync currently in flight (defensive — sync is modal,
        # so it normally can't be running when this binding fires, but if it ever
        # is we want to stop yt-dlp at the next checkpoint).
        for screen in list(self.app.screen_stack):
            if isinstance(screen, SyncScreen):
                screen._cancel.set()
        # Close-to-tray: launch a detached tray process before exiting so USB
        # plug events + sync keep running while the TUI is gone.
        if getattr(self.config, "close_to_tray", False):
            from ..tray import spawn_detached
            ok, _msg = spawn_detached()
            if ok:
                self.app.notify("Mixtape is now in the system tray.", timeout=4)
        # Show "Fermeture en cours…" popup, then exit shortly after so the user
        # sees it and the terminal teardown doesn't feel like a freeze.
        self.app.push_screen(QuittingScreen())
        self.app.set_timer(0.4, self.app.exit)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield Static("", id="status-bar")
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "mixtape"
        self.sub_title = "YouTube Music playlist sync"
        table = self.query_one(DataTable)
        table.add_columns("#", "Name", "Format", "Last sync", "Tracks", "Folder")
        self._refresh_table()
        self._refresh_status()

    def _refresh_status(self) -> None:
        bg = bgutil_server_path()
        playlists = self.config.active_playlists()
        n = len(playlists)
        cookie_status = self.app.cookie_status  # type: ignore[attr-defined]
        if cookie_status.state == "valid":
            cookie_str = "[green]✓ cookies valid[/green]"
        elif cookie_status.state == "missing":
            cookie_str = "[red]✗ no cookies (sync blocked) — press 'c'[/red]"
        elif cookie_status.state == "expired":
            cookie_str = "[red]✗ cookies expired (sync blocked) — re-paste via 'c'[/red]"
        elif cookie_status.state == "unknown":
            cookie_str = "[yellow]… checking cookies[/yellow]" if cookie_status.message == "checking…" else f"[yellow]? cookies: {cookie_status.message}[/yellow]"
        else:
            cookie_str = f"[red]? cookies: {cookie_status.state}[/red]"
        bgutil_status, bgutil_msg = self.app.bgutil_status  # type: ignore[attr-defined]
        if not bg:
            companion_str = "[yellow]bgutil companion not set up[/yellow]"
        elif bgutil_status == "ok":
            companion_str = "[green]✓ bgutil companion[/green]"
        else:
            companion_str = f"[red]✗ bgutil: {bgutil_msg}[/red]"
        active_lib = self.config.active_library_obj()
        # Update banner — only shown when there's actually something to update.
        # The "[Update now]" suffix is a Textual click action that opens the
        # UpdateScreen modal (same as pressing 'u').
        update_status = getattr(self.app, "update_status", None)
        update_str = ""
        if update_status and update_status.has_update:
            arrow = "↑"
            if update_status.channel == "stable":
                summary = f"{arrow} update {update_status.latest} available"
            else:  # dev
                summary = f"{arrow} {update_status.message}"
            update_str = (
                f" — [b yellow]{summary}[/b yellow] "
                f"[@click=screen.update][b reverse] Update now [/b reverse][/]"
            )
        self.query_one("#status-bar", Static).update(
            f"{n} playlist(s) — {cookie_str} — {companion_str} — "
            f"library: [b cyan]{active_lib.name}[/b cyan] [dim]({active_lib.path})[/dim]"
            f"{update_str}"
        )

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for i, p in enumerate(self.config.active_playlists()):
            last = p.last_sync or "—"
            tracks = str(p.track_count) if p.track_count else "—"
            folder = p.relative_path or _slugify(p.name)
            fmt_label = p.format if p.requires_cookies else f"{p.format} [dim](public)[/dim]"
            table.add_row(str(i + 1), p.name, fmt_label, last, tracks, folder, key=str(i))

    def _selected_index(self) -> int | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        if row_key.value is None:
            return None
        try:
            return int(row_key.value)
        except (ValueError, TypeError):
            return None

    # --- actions ---

    def action_add(self) -> None:
        def cb(result) -> None:
            if result is not None:
                self.config.add_playlist(result)
                self._refresh_table()
                self._refresh_status()
                self.notify(f"Added '{result.name}'")
        self.app.push_screen(AddPlaylistScreen(self.config), cb)

    def action_edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.notify("Nothing selected.", severity="warning")
            return
        playlists = self.config.active_playlists()
        if idx >= len(playlists):
            return
        existing = playlists[idx]
        screen = AddPlaylistScreen(self.config, prefilled_url=existing.url)

        def cb(result) -> None:
            if result is not None:
                # Preserve the existing folder identity so the on-disk dir
                # doesn't move around when the user just retyped the name.
                if not result.relative_path and existing.relative_path:
                    result.relative_path = existing.relative_path
                self.config.update_playlist(result)
                self._refresh_table()
                self.notify(f"Updated '{result.name}'")
        self.app.push_screen(screen, cb)

    def action_delete(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.notify("Nothing selected.", severity="warning")
            return
        playlists = self.config.active_playlists()
        if idx >= len(playlists):
            return
        playlist = playlists[idx]
        active_lib = self.config.active_library_obj()
        playlist_dir = playlist.expanded_dir_for(active_lib)

        def cb(result: DeleteResult | None) -> None:
            if result is None or not result.confirmed:
                return
            name = playlist.name
            self.config.remove_playlist(playlist, also_files=bool(result.delete_folder))
            self._refresh_table()
            self._refresh_status()
            if result.delete_folder:
                self.notify(f"Deleted '{name}' (folder removed).")
            else:
                self.notify(f"Removed '{name}' from this library (audio files kept).")

        self.app.push_screen(ConfirmDeleteScreen(playlist.name, str(playlist_dir)), cb)

    def action_cookies(self) -> None:
        def cb(_):
            self._refresh_status()
        self.app.push_screen(CookiesScreen(), cb)

    def action_import_lib(self) -> None:
        def cb(result):
            if result:
                for p in result:
                    self.config.add_playlist(p)
                self._refresh_table()
                self._refresh_status()
                self.notify(f"Imported {len(result)} playlist(s)")
        self.app.push_screen(ImportLibraryScreen(self.config), cb)

    def action_sync_one(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.notify("Nothing selected.", severity="warning")
            return
        playlists = self.config.active_playlists()
        if idx >= len(playlists):
            return
        targets = [(idx, playlists[idx])]
        self._run_sync(targets)

    def action_sync_all(self) -> None:
        playlists = self.config.active_playlists()
        if not playlists:
            self.notify("No playlists configured.", severity="warning")
            return
        targets = [(i, p) for i, p in enumerate(playlists)]
        self._run_sync(targets)

    def _run_sync(self, targets) -> None:
        # Per-playlist cookie gate. A playlist with requires_cookies=True is
        # blocked when cookies are invalid (best-quality guarantee). One with
        # requires_cookies=False is allowed through (public-tier audio is fine).
        cookie_status = self.app.cookie_status  # type: ignore[attr-defined]
        if not cookie_status.ok:
            cookie_required = [(i, p) for i, p in targets if p.requires_cookies]
            anonymous = [(i, p) for i, p in targets if not p.requires_cookies]
            if cookie_required and not anonymous:
                self.notify(
                    f"Sync blocked: {cookie_status.message}. Press 'c' to fix, "
                    f"or uncheck 'Cookies required' on a playlist for public-quality sync.",
                    severity="error", timeout=10,
                )
                return
            if cookie_required:
                self.notify(
                    f"{len(cookie_required)} cookie-required playlist(s) skipped — "
                    f"syncing the {len(anonymous)} anonymous-mode one(s) only.",
                    severity="warning", timeout=8,
                )
            targets = anonymous

        def cb(_):
            # The active library can change mid-sync (USB unplug → fallback),
            # so reload it from the app — playlist table + status bar both
            # depend on it.
            self.config = self.app.config  # type: ignore[attr-defined]
            self._refresh_table()
            self._refresh_status()
            try:
                self.app.recheck_cookies()  # type: ignore[attr-defined]
            except AttributeError:
                pass
        self.app.push_screen(SyncScreen(self.config, targets), cb)

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_update(self) -> None:
        def cb(_):
            self._refresh_status()
        self.app.push_screen(UpdateScreen(), cb)

    def action_libraries(self) -> None:
        def cb(_):
            # Active library may have changed → reload from disk + repaint
            self.config = Config.load()
            self.app.config = self.config  # type: ignore[attr-defined]
            self._refresh_table()
            self._refresh_status()
        self.app.push_screen(LibrariesScreen(self.config), cb)

