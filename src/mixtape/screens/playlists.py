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
from .sync import SyncScreen


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
        Binding("r", "refresh", "Refresh"),
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
        n = len(self.config.playlists)
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
        update_status = getattr(self.app, "update_status", None)
        update_str = ""
        if update_status and update_status.has_update:
            install_cmd = (
                "irm https://raw.githubusercontent.com/cinhil/mixtape/main/install.ps1 | iex"
                if self.app.platform == "windows"  # type: ignore[attr-defined]
                else "curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash"
            )
            channel = update_status.channel
            arrow = "↑"
            if channel == "stable":
                update_str = (
                    f" — [b yellow]{arrow} update {update_status.latest} available[/b yellow] "
                    f"[dim](run: {install_cmd})[/dim]"
                )
            else:  # dev
                update_str = (
                    f" — [b yellow]{arrow} {update_status.message}[/b yellow] "
                    f"[dim](run: {install_cmd} -- --dev)[/dim]"
                )
        self.query_one("#status-bar", Static).update(
            f"{n} playlist(s) — {cookie_str} — {companion_str} — "
            f"library: [b cyan]{active_lib.name}[/b cyan] [dim]({active_lib.path})[/dim]"
            f"{update_str}"
        )

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        active_lib = self.config.active_library_obj()
        for i, p in enumerate(self.config.playlists):
            last = p.last_sync or "—"
            tracks = str(p.track_count) if p.track_count else "—"
            folder = p.relative_path or _slugify(p.name)
            table.add_row(str(i + 1), p.name, p.format, last, tracks, folder, key=str(i))

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
        existing = self.config.playlists[idx]
        screen = AddPlaylistScreen(self.config, prefilled_url=existing.url)

        def cb(result) -> None:
            if result is not None:
                self.config.update_playlist(idx, result)
                self._refresh_table()
                self.notify(f"Updated '{result.name}'")
        self.app.push_screen(screen, cb)

    def action_delete(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.notify("Nothing selected.", severity="warning")
            return
        playlist = self.config.playlists[idx]

        active_lib = self.config.active_library_obj()
        playlist_dir = playlist.expanded_dir_for(active_lib)

        def cb(result: DeleteResult | None) -> None:
            if result is None or not result.confirmed:
                return
            name = playlist.name
            if result.delete_folder:
                if playlist_dir.exists():
                    try:
                        shutil.rmtree(playlist_dir)
                        self.notify(f"Folder removed: {playlist_dir}")
                    except OSError as e:
                        self.notify(f"Could not remove folder: {e}", severity="error")
                        return
            self.config.remove_playlist(idx)
            self._refresh_table()
            self._refresh_status()
            self.notify(f"Deleted '{name}'")

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
        targets = [(idx, self.config.playlists[idx])]
        self._run_sync(targets)

    def action_sync_all(self) -> None:
        if not self.config.playlists:
            self.notify("No playlists configured.", severity="warning")
            return
        targets = [(i, p) for i, p in enumerate(self.config.playlists)]
        self._run_sync(targets)

    def _run_sync(self, targets) -> None:
        # Gate: never download without valid cookies (per user policy: best
        # quality requires authenticated access).
        cookie_status = self.app.cookie_status  # type: ignore[attr-defined]
        if not cookie_status.ok:
            self.notify(
                f"Sync blocked: {cookie_status.message}. Press 'c' to fix.",
                severity="error",
                timeout=8,
            )
            return

        def cb(_):
            self._refresh_table()
            # Re-check cookies after a sync — they may have been refreshed (or
            # invalidated server-side) during long-running downloads.
            try:
                self.app.recheck_cookies()  # type: ignore[attr-defined]
            except AttributeError:
                pass
        self.app.push_screen(SyncScreen(self.config, targets), cb)

    def action_refresh(self) -> None:
        self.config = Config.load()
        self._refresh_table()
        self._refresh_status()

    def action_libraries(self) -> None:
        def cb(_):
            # Active library may have changed → reload from disk + repaint
            self.config = Config.load()
            self.app.config = self.config  # type: ignore[attr-defined]
            self._refresh_table()
            self._refresh_status()
        self.app.push_screen(LibrariesScreen(self.config), cb)

