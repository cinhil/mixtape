"""Cookie paste form — modal screen for the new TUI."""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, TextArea

from ...client import DaemonClient, DaemonError


class CookiesScreen(ModalScreen[bool]):
    """Paste a Netscape ``cookies.txt`` and let the daemon validate it.

    Returns True if cookies were accepted, False otherwise."""

    CSS = """
    CookiesScreen { align: center middle; }
    #dialog {
        width: 96; height: 30;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    #title { height: 1; }
    #hint { color: $text-muted; height: auto; min-height: 1; margin: 0 0 1 0; }
    #pasted { height: 1fr; border: round $panel; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Cancel"),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]

    def __init__(self, client: DaemonClient) -> None:
        super().__init__()
        self._client = client
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Paste cookies.txt[/b]", id="title")
            yield Static(
                "Use a browser extension like [i]Get cookies.txt LOCALLY[/i] on "
                "music.youtube.com, then paste the file here. Ctrl+S to save.",
                id="hint",
            )
            yield TextArea(id="pasted", language=None)
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
            self.dismiss(False)

    async def action_save(self) -> None:
        if self._busy:
            return
        text = self.query_one("#pasted", TextArea).text
        status = self.query_one("#status", Static)
        if not text.strip():
            status.update("[yellow]Empty — paste cookies.txt content first.[/yellow]")
            return
        self._busy = True
        status.update("[yellow]… validating[/yellow]")
        try:
            result: dict[str, Any] = await self._client.set_cookies(text)
        except DaemonError as e:
            status.update(f"[red]✗ {e}[/red]")
            self._busy = False
            return
        if result.get("ok"):
            status.update(f"[green]✓ {result.get('message','cookies valid')}[/green]")
            self.set_timer(0.6, lambda: self.dismiss(True))
        else:
            status.update(f"[red]✗ {result.get('message','rejected')}[/red]")
            self._busy = False
