"""TUI entry point + main app shell.

Bootstrap order:
  1. Connect to (or auto-spawn) the daemon via DaemonClient.connect().
  2. Mount the dashboard screen.
  3. Subscribe to WS events; route them to whichever screen is active.

This shell is intentionally minimal — it covers the core flows
(dashboard → sync, libraries, cookies, settings) and depends on the
daemon for everything domain-related. Screens are simple and don't
hold their own state."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable, Footer, Header, Static, ProgressBar, RichLog,
)

from ..client import DaemonClient, DaemonError, DaemonNotRunning


log = logging.getLogger("mixtape.tui")


class MixtapeTUI(App):
    """Mixtape's daemon-driven TUI.

    Holds a long-lived ``self.client`` connection. Subscribes to the
    daemon's WS event stream once and dispatches events to the active
    screen by handler-name convention (``on_daemon_event``)."""

    CSS = """
    Screen { background: $background; }
    #status-bar { height: 1; padding: 0 1; color: $text-muted; }
    DataTable { height: 1fr; }
    #log { height: 12; border: round $panel; }
    .panel { border: round $panel; padding: 0 1; margin: 0 0 1 0; }
    .pl-row { height: 4; margin: 0 0 1 0; border: round $panel; padding: 0 1; }
    .pl-name { height: 1; }
    .pl-status { height: 1; color: $text-muted; }
    .pl-bar { height: 1; }
    """

    TITLE = "mixtape"
    SUB_TITLE = "daemon-driven"

    BINDINGS = [
        Binding("a", "noop", "Add"),
        Binding("e", "noop", "Edit"),
        Binding("d", "noop", "Delete"),
        Binding("s", "sync_one", "Sync sel."),
        Binding("S", "sync_all", "Sync all"),
        Binding("c", "refresh_cookies", "Refresh cookies"),
        Binding("u", "refresh_update", "Update?"),
        Binding("r", "refresh_state", "Reload"),
        Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
        Binding("q", "quit_app", "Quit", priority=True),
    ]

    def __init__(self, client: DaemonClient) -> None:
        super().__init__()
        self.client = client
        self.state: dict[str, Any] = {}
        self.libraries: dict[str, Any] = {}
        self.playlists: list[dict[str, Any]] = []

    # ── lifecycle ──────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield Static("Connecting to daemon…", id="status-bar")
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
            yield RichLog(id="log", highlight=True, markup=True, max_lines=400)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("#", "Name", "Format", "Last sync", "Tracks", "Folder")
        self.refresh_state()
        self._stream_events()

    # ── event handlers ────────────────────────────────────────────────

    @work(thread=False, exclusive=True)
    async def _stream_events(self) -> None:
        log_w = self.query_one("#log", RichLog)
        try:
            async for ev in self.client.stream_events_forever():
                self._handle_event(ev)
        except asyncio.CancelledError:
            return
        except Exception as e:  # noqa: BLE001
            log_w.write(f"[red]event stream errored: {e}[/red]")

    def _handle_event(self, ev: dict[str, Any]) -> None:
        log_w = self.query_one("#log", RichLog)
        name = ev.get("name", "")
        data = ev.get("data", {})
        if name == "sync.started":
            n = len(data.get("playlists", []))
            log_w.write(f"[cyan]▶[/cyan] sync started — {n} playlist(s) on [b]{data.get('library')}[/b]")
        elif name == "sync.progress":
            # Don't log every chunk — they're chatty.
            pass
        elif name == "sync.track_done":
            log_w.write(
                f"  [green]✓[/green] {data.get('track_idx')}/{data.get('track_total')} "
                f"{data.get('track_title','?')}"
            )
        elif name == "sync.playlist_done":
            log_w.write(f"[green]✔[/green] {data.get('name')} ({data.get('count')} tracks)")
        elif name == "sync.error":
            log_w.write(f"[red]✗[/red] {data.get('message','?')}")
        elif name == "sync.finished":
            tag = "[green]done[/green]" if data.get("ok") else "[yellow]cancelled[/yellow]"
            log_w.write(f"[b]{tag}[/b] — refreshing playlist table")
            self.refresh_state()
        elif name == "library.changed":
            self.refresh_state()
        elif name == "cookies.status":
            self._set_status_bar()
        elif name == "bgutil.status":
            self._set_status_bar()
        elif name == "update.status":
            self._set_status_bar()
        elif name == "volume.added":
            log_w.write(f"[cyan]🔌[/cyan] volume plugged: {data.get('label') or data.get('identifier')}")
        elif name == "volume.removed":
            log_w.write(f"[cyan]📤[/cyan] volume unplugged: {data.get('identifier')}")
        elif name == "daemon.shutdown":
            log_w.write("[red]daemon shut down — quitting[/red]")
            self.set_timer(0.2, self.exit)
        else:
            log_w.write(f"[dim]· {name}[/dim]")

    @work(thread=False, exclusive=True, group="state")
    async def refresh_state(self) -> None:
        try:
            self.state = await self.client.status()
            self.libraries = await self.client.libraries()
            self.playlists = await self.client.playlists()
        except DaemonError as e:
            self._log(f"[red]daemon error: {e}[/red]")
            return
        self._set_status_bar()
        self._refresh_table()

    def _set_status_bar(self) -> None:
        bgutil = self.state.get("bgutil", {})
        cookies = self.state.get("cookies", {})
        active = self.libraries.get("active", "?")
        update = self.state.get("update")

        if cookies.get("state") == "valid":
            cookie_str = "[green]✓ cookies valid[/green]"
        elif cookies.get("state") in ("missing", "expired"):
            cookie_str = f"[red]✗ cookies {cookies['state']} — press 'c'[/red]"
        else:
            cookie_str = f"[yellow]? cookies: {cookies.get('message','')}[/yellow]"

        if bgutil.get("state") == "ok":
            bg_str = "[green]✓ bgutil[/green]"
        else:
            bg_str = f"[red]✗ bgutil: {bgutil.get('message','?')}[/red]"

        n = len(self.playlists)
        update_str = ""
        if update and update.get("behind"):
            update_str = f" — [b yellow]↑ {update.get('message','update')}[/b yellow]"

        bar = self.query_one("#status-bar", Static)
        bar.update(
            f"{n} playlist(s) — {cookie_str} — {bg_str} — "
            f"library: [b cyan]{active}[/b cyan]{update_str}"
        )

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for i, p in enumerate(self.playlists):
            last = p.get("last_sync") or "—"
            tracks = str(p.get("track_count") or "—")
            folder = p.get("relative_path") or _slug(p.get("name", ""))
            fmt = p.get("format", "?")
            if not p.get("requires_cookies"):
                fmt = f"{fmt} [dim](public)[/dim]"
            table.add_row(str(i + 1), p.get("name", "?"), fmt, last, tracks, folder, key=str(i))

    def _log(self, markup: str) -> None:
        try:
            self.query_one("#log", RichLog).write(markup)
        except Exception:
            pass

    # ── actions ────────────────────────────────────────────────────────

    def action_noop(self) -> None:
        # Edit/Add/Delete: not yet ported to the daemon client.
        self._log("[dim]Add/Edit/Delete via daemon client not yet implemented.[/dim]")

    @work(thread=False, exclusive=True, group="action")
    async def action_sync_one(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self._log("[yellow]Nothing selected.[/yellow]")
            return
        try:
            await self.client.sync(playlists=[idx])
        except DaemonError as e:
            self._log(f"[red]sync failed: {e}[/red]")

    @work(thread=False, exclusive=True, group="action")
    async def action_sync_all(self) -> None:
        try:
            await self.client.sync()
        except DaemonError as e:
            self._log(f"[red]sync failed: {e}[/red]")

    @work(thread=False, exclusive=True, group="action")
    async def action_refresh_cookies(self) -> None:
        await self.client.refresh_cookies()

    @work(thread=False, exclusive=True, group="action")
    async def action_refresh_update(self) -> None:
        await self.client.refresh_update()

    def action_refresh_state(self) -> None:
        self.refresh_state()

    def action_quit_app(self) -> None:
        self.exit()

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


def _slug(name: str) -> str:
    import re
    s = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"\s+", " ", s) or "playlist"


def run_tui() -> int:
    """Entry-point body — connect to the daemon, then run the app."""
    async def _connect() -> DaemonClient:
        try:
            return await DaemonClient.connect()
        except DaemonNotRunning as e:
            print(f"Could not start the mixtape daemon: {e}", flush=True)
            raise SystemExit(2) from e

    client = asyncio.run(_connect())
    app = MixtapeTUI(client)
    try:
        app.run()
    finally:
        try:
            asyncio.run(client.aclose())
        except Exception:
            pass
    return 0
