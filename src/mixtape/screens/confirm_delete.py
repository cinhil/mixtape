from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static
from ..widgets import Checkbox


@dataclass
class DeleteResult:
    confirmed: bool
    delete_folder: bool


class ConfirmDeleteScreen(ModalScreen[DeleteResult]):
    """Confirm deletion of a playlist + offer to wipe its folder."""

    CSS = """
    ConfirmDeleteScreen { align: center middle; }
    #dialog {
        width: 70; height: auto;
        border: round $error; background: $surface;
        padding: 1 2;
    }
    #title { height: 1; }
    #info { color: $text-muted; height: auto; margin: 1 0; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    Checkbox { margin: 1 0; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "confirm", "Confirm"),
    ]

    def __init__(self, playlist_name: str, output_dir: str) -> None:
        super().__init__()
        self.playlist_name = playlist_name
        self.output_dir = output_dir

    def compose(self) -> ComposeResult:
        path = Path(self.output_dir).expanduser()
        exists = path.exists()
        size_info = ""
        if exists:
            try:
                files = [f for f in path.rglob("*") if f.is_file()]
                total = sum(f.stat().st_size for f in files)
                size_info = f" ({len(files)} fichiers, {total / 1_048_576:.1f} MB)"
            except OSError:
                size_info = ""

        with Vertical(id="dialog"):
            yield Label(f"[b red]Supprimer[/b red] [b]{self.playlist_name}[/b] ?", id="title")
            yield Static(
                f"Le dossier sur disque :\n[cyan]{path}[/cyan]\n"
                f"{'existe' + size_info if exists else '[dim](dossier inexistant)[/dim]'}",
                id="info",
            )
            yield Checkbox(
                "Aussi effacer le dossier et tous les fichiers audio",
                value=False,
                id="wipe",
                disabled=not exists,
            )
            with Horizontal(id="buttons"):
                yield Button("Supprimer (Ctrl+S)", id="confirm", variant="error")
                yield Button("Annuler (Esc)", id="cancel")
        yield Footer()

    def action_confirm(self) -> None:
        wipe = self.query_one("#wipe", Checkbox).value
        self.dismiss(DeleteResult(confirmed=True, delete_folder=bool(wipe)))

    def action_cancel(self) -> None:
        self.dismiss(DeleteResult(confirmed=False, delete_folder=False))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.action_confirm()
        else:
            self.action_cancel()
