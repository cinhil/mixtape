from __future__ import annotations

import threading

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, LoadingIndicator, SelectionList, Static

from ..config import Config, Playlist
from ..downloader import PlaylistMeta, list_user_library
from ..config import _slugify


class ImportLibraryScreen(ModalScreen[list[Playlist] | None]):
    """Fetch user's YouTube playlists (cookies required) and let them pick."""

    CSS = """
    ImportLibraryScreen { align: center middle; }
    #dialog {
        width: 90%; height: 90%;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 0 0 1 0; }
    #list { height: 1fr; }
    #buttons { height: 3; align: center middle; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Import"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._items: list[PlaylistMeta] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Importer depuis ton compte YouTube[/b]")
            yield Static("Fetching playlists…", id="status")
            yield LoadingIndicator(id="loader")
            yield SelectionList[int](id="list")
            with Horizontal(id="buttons"):
                yield Button("Importer la sélection (Ctrl+S)", id="save", variant="success")
                yield Button("Cancel (Esc)", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#list", SelectionList).display = False
        self._fetch_worker()

    def _fetch_worker(self) -> None:
        def run() -> None:
            try:
                items = list_user_library()
            except Exception as e:  # noqa: BLE001
                self.app.call_from_thread(self._on_error, str(e))
                return
            self.app.call_from_thread(self._on_done, items)

        threading.Thread(target=run, name="fetch-library", daemon=True).start()

    def _on_done(self, items: list[PlaylistMeta]) -> None:
        self.query_one("#loader", LoadingIndicator).display = False
        self.query_one("#list", SelectionList).display = True
        self._items = items
        sel = self.query_one("#list", SelectionList)
        for i, m in enumerate(items):
            label = f"{m.title}  [dim]({m.count or '?'} tracks)[/dim]"
            sel.add_option((label, i))
        if not items:
            self.query_one("#status", Static).update("[yellow]No playlists found.[/yellow]")
        else:
            self.query_one("#status", Static).update(f"{len(items)} playlists found. Space to select, Ctrl+S to import.")

    def _on_error(self, msg: str) -> None:
        self.query_one("#loader", LoadingIndicator).display = False
        self.query_one("#status", Static).update(f"[red]Error: {msg}[/red]\n[dim]Need cookies? Press 'c' on main screen.[/dim]")

    def action_save(self) -> None:
        selected: list[int] = list(self.query_one("#list", SelectionList).selected)
        if not selected:
            self.app.notify("Nothing selected.", severity="warning")
            return
        d = self.config.defaults
        playlists = [
            Playlist(
                name=self._items[i].title,
                url=self._items[i].url,
                relative_path=_slugify(self._items[i].title),
                format=d.format,
                quality=d.quality,
            )
            for i in selected
        ]
        self.dismiss(playlists)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()
