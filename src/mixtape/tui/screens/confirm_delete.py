"""Confirm deletion of a playlist (with optional 'also delete files')."""
from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Label, Static


@dataclass
class DeleteConfirmation:
    confirmed: bool
    delete_files: bool = False


class ConfirmDeleteScreen(ModalScreen[DeleteConfirmation]):
    CSS = """
    ConfirmDeleteScreen { align: center middle; }
    #dialog {
        width: 80; height: auto;
        border: round $error; background: $surface;
        padding: 1 2;
    }
    #title { height: 1; }
    #info { color: $text-muted; margin: 1 0; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    Checkbox { margin: 0 0 1 0; }
    """

    BINDINGS = [
        Binding("escape", "close", "Cancel"),
        Binding("y", "confirm", "Confirm", priority=False),
    ]

    def __init__(self, name: str, folder: str) -> None:
        super().__init__()
        self._name = name
        self._folder = folder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[b red]Delete playlist '{self._name}'?[/b red]")
            yield Static(
                f"Folder on disk: [b]{self._folder}[/b]",
                id="info",
            )
            yield Checkbox(
                "Also delete the audio files on disk (irreversible)",
                value=False, id="also_files",
            )
            with Horizontal(id="buttons"):
                yield Button("Delete", id="delete", variant="error")
                yield Button("Cancel (Esc)", id="cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete":
            self.action_confirm()
        elif event.button.id == "cancel":
            self.action_close()

    def action_close(self) -> None:
        self.dismiss(DeleteConfirmation(confirmed=False))

    def action_confirm(self) -> None:
        also = self.query_one("#also_files", Checkbox).value
        self.dismiss(DeleteConfirmation(confirmed=True, delete_files=bool(also)))
