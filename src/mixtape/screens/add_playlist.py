from __future__ import annotations

import threading

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Input, Label, LoadingIndicator, Select, Static

from ..config import Config, Playlist, _slugify
from ..downloader import PlaylistMeta, fetch_playlist_meta

FORMAT_OPTIONS = [
    ("MP3 (compatible vieux lecteurs)", "mp3"),
    ("M4A/AAC (qualité, récent)", "m4a"),
    ("Opus (best efficiency)", "opus"),
    ("FLAC (sans perte)", "flac"),
]

QUALITY_OPTIONS = [
    ("Meilleure (VBR, recommandé)", "0"),
    ("320 kbps (haute, gros fichiers)", "320"),
    ("256 kbps", "256"),
    ("192 kbps (standard)", "192"),
    ("128 kbps (petit, basique)", "128"),
]


class AddPlaylistScreen(ModalScreen[Playlist | None]):
    """Add a playlist by URL. Auto-fetches its title."""

    CSS = """
    AddPlaylistScreen { align: center middle; }
    #dialog {
        width: 80; height: auto; max-height: 90%;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .row { height: auto; margin: 0 0 1 0; }
    .label { width: 16; }
    Input, Select { width: 1fr; }
    #buttons { height: 3; align: center middle; }
    Button { margin: 0 1; }
    #status { color: $text-muted; height: auto; min-height: 1; }
    #loader { height: 3; align: center middle; display: none; }
    .visible { display: block !important; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, config: Config, prefilled_url: str | None = None) -> None:
        super().__init__()
        self.config = config
        self.prefilled_url = prefilled_url
        self._meta: PlaylistMeta | None = None

    def compose(self) -> ComposeResult:
        d = self.config.defaults
        with Vertical(id="dialog"):
            yield Label("[b]Ajouter une playlist[/b]")
            with Horizontal(classes="row"):
                yield Label("URL", classes="label")
                yield Input(value=self.prefilled_url or "", id="url", placeholder="https://music.youtube.com/playlist?list=...")
            with Horizontal(classes="row"):
                yield Button("Récupérer le titre", id="fetch", variant="primary")
                yield Static("", id="status")
            yield LoadingIndicator(id="loader")
            with Horizontal(classes="row"):
                yield Label("Nom", classes="label")
                yield Input(value="", id="name", placeholder="(auto depuis YouTube)")
            with Horizontal(classes="row"):
                yield Label("Format", classes="label")
                yield Select(FORMAT_OPTIONS, value=d.format, id="format", allow_blank=False)
            with Horizontal(classes="row"):
                yield Label("Qualité", classes="label")
                quality_value = d.quality if any(d.quality == v for _, v in QUALITY_OPTIONS) else "0"
                yield Select(QUALITY_OPTIONS, value=quality_value, id="quality", allow_blank=False)
            with Horizontal(classes="row"):
                yield Label("Sous-dossier", classes="label")
                yield Input(
                    value="",
                    id="relative_path",
                    placeholder="(auto: nom slugifié, sous le dossier de la library active)",
                )
            with Horizontal(classes="row"):
                yield Checkbox(
                    "Cookies requis (qualité haute garantie — décocher pour les playlists publiques)",
                    value=True,
                    id="requires_cookies",
                )
            with Horizontal(id="buttons"):
                yield Button("Save (Ctrl+S)", id="save", variant="success")
                yield Button("Cancel (Esc)", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = False
        if self.prefilled_url:
            self.action_fetch()

    def _fetch_worker(self, url: str) -> None:
        """Run fetch in a daemon thread so a pending fetch doesn't block app exit."""

        def run() -> None:
            try:
                meta = fetch_playlist_meta(url)
            except Exception as e:  # noqa: BLE001
                self.app.call_from_thread(self._on_fetch_error, str(e))
                return
            self.app.call_from_thread(self._on_fetch_done, meta)

        threading.Thread(target=run, name="fetch-meta", daemon=True).start()

    def action_fetch(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if not url:
            self.app.notify("Enter a URL first.", severity="warning")
            return
        self.query_one("#status", Static).update("Fetching…")
        self.query_one("#loader", LoadingIndicator).display = True
        self._fetch_worker(url)

    def _on_fetch_done(self, meta: PlaylistMeta) -> None:
        self._meta = meta
        self.query_one("#loader", LoadingIndicator).display = False
        self.query_one("#status", Static).update(f"[green]✓[/green] '{meta.title}' — {meta.count} tracks")
        name_input = self.query_one("#name", Input)
        if not name_input.value:
            name_input.value = meta.title
        rel_input = self.query_one("#relative_path", Input)
        if not rel_input.value:
            rel_input.value = _slugify(meta.title)

    def _on_fetch_error(self, msg: str) -> None:
        self.query_one("#loader", LoadingIndicator).display = False
        self.query_one("#status", Static).update(f"[red]✗ {msg}[/red]")

    def action_save(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        name = self.query_one("#name", Input).value.strip()
        fmt = self.query_one("#format", Select).value
        quality = self.query_one("#quality", Select).value
        relative_path = self.query_one("#relative_path", Input).value.strip()
        requires_cookies = self.query_one("#requires_cookies", Checkbox).value
        if not url or not name:
            self.app.notify("URL and name are required.", severity="error")
            return
        if fmt is Select.BLANK or quality is Select.BLANK:
            self.app.notify("Pick a format and quality.", severity="error")
            return
        playlist = Playlist(
            name=name, url=url, format=str(fmt), quality=str(quality),
            relative_path=relative_path,
            requires_cookies=bool(requires_cookies),
        )
        self.dismiss(playlist)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "fetch":
            self.action_fetch()
        elif bid == "save":
            self.action_save()
        elif bid == "cancel":
            self.action_cancel()
