"""Add / Edit playlist form for the new TUI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Input, Label, Select, Static

from ...client import DaemonClient, DaemonError


FORMATS = [("mp3", "mp3"), ("m4a", "m4a"), ("opus", "opus"), ("flac", "flac")]
QUALITIES = [
    ("0 (best)", "0"),
    ("2", "2"),
    ("4", "4"),
    ("6", "6"),
    ("9 (smallest)", "9"),
]


@dataclass
class PlaylistFormResult:
    saved: bool
    payload: dict[str, Any] | None = None


class PlaylistFormScreen(ModalScreen[PlaylistFormResult]):
    """Add or edit a playlist. Set ``edit`` (and ``edit_idx``) to switch
    to edit mode; otherwise it's an add."""

    CSS = """
    PlaylistFormScreen { align: center middle; }
    #dialog {
        width: 90; height: auto;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .row { height: 3; margin: 0 0 1 0; }
    .row Input, .row Select { width: 1fr; }
    .label { width: 18; padding-top: 1; color: $text-muted; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Cancel"),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]

    def __init__(self, client: DaemonClient,
                 *, edit: dict[str, Any] | None = None,
                 edit_idx: int | None = None) -> None:
        super().__init__()
        self._client = client
        self._edit = edit
        self._edit_idx = edit_idx
        self._busy = False

    @property
    def title_text(self) -> str:
        return "Edit playlist" if self._edit else "Add playlist"

    def compose(self) -> ComposeResult:
        url_default = (self._edit or {}).get("url", "")
        name_default = (self._edit or {}).get("name", "")
        fmt_default = (self._edit or {}).get("format", "mp3")
        q_default = (self._edit or {}).get("quality", "0")
        rc_default = bool((self._edit or {}).get("requires_cookies", True))
        with Vertical(id="dialog"):
            yield Label(f"[b]{self.title_text}[/b]")
            with Horizontal(classes="row"):
                yield Static("URL", classes="label")
                yield Input(value=url_default, id="url",
                            placeholder="https://music.youtube.com/playlist?list=…",
                            disabled=self._edit is not None)
            with Horizontal(classes="row"):
                yield Static("Name (auto)", classes="label")
                yield Input(value=name_default, id="name",
                            placeholder="leave empty to fetch from YouTube")
            with Horizontal(classes="row"):
                yield Static("Format", classes="label")
                yield Select(FORMATS, value=fmt_default, id="format", allow_blank=False)
            with Horizontal(classes="row"):
                yield Static("Quality", classes="label")
                yield Select(QUALITIES, value=q_default, id="quality", allow_blank=False)
            with Horizontal(classes="row"):
                yield Static("Cookies", classes="label")
                yield Checkbox("Requires cookies (best-quality YouTube Music)",
                               value=rc_default, id="requires_cookies")
            yield Static("", id="status")
            with Horizontal(id="buttons"):
                yield Button("Save (Ctrl+S)", id="save", variant="primary")
                yield Button("Cancel (Esc)", id="cancel")
        yield Footer()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy:
            return
        if event.button.id == "save":
            await self.action_save()
        elif event.button.id == "cancel":
            self.action_close()

    def action_close(self) -> None:
        if not self._busy:
            self.dismiss(PlaylistFormResult(saved=False))

    async def action_save(self) -> None:
        if self._busy:
            return
        url = self.query_one("#url", Input).value.strip()
        name = self.query_one("#name", Input).value.strip() or None
        fmt = str(self.query_one("#format", Select).value)
        quality = str(self.query_one("#quality", Select).value)
        requires_cookies = bool(self.query_one("#requires_cookies", Checkbox).value)
        status = self.query_one("#status", Static)
        if not url and not self._edit:
            status.update("[yellow]URL is required.[/yellow]")
            return
        self._busy = True
        status.update("[yellow]… saving[/yellow]")
        try:
            if self._edit is not None and self._edit_idx is not None:
                payload = await self._client.update_playlist(
                    self._edit_idx, name=name, fmt=fmt, quality=quality,
                    requires_cookies=requires_cookies,
                )
            else:
                payload = await self._client.add_playlist(
                    url, name=name, fmt=fmt, quality=quality,
                    requires_cookies=requires_cookies,
                )
        except DaemonError as e:
            status.update(f"[red]✗ {e}[/red]")
            self._busy = False
            return
        status.update(f"[green]✓ saved {payload.get('name','?')}[/green]")
        self.set_timer(0.4, lambda: self.dismiss(
            PlaylistFormResult(saved=True, payload=payload)
        ))
