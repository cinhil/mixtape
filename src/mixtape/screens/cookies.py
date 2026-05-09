from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, TextArea

from ..config import COOKIES_FILE, cookies_path, write_cookies


class CookiesScreen(ModalScreen[bool]):
    """Modal to paste Netscape-format cookies.txt content."""

    CSS = """
    CookiesScreen {
        align: center middle;
    }
    #cookies-dialog {
        width: 90%;
        height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #cookies-area {
        height: 1fr;
        margin: 1 0;
    }
    #cookies-buttons {
        height: 3;
        align: center middle;
    }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="cookies-dialog"):
            yield Label("[b]Coller le contenu de cookies.txt (format Netscape)[/b]")
            yield Static(
                "Extension recommandée: 'Get cookies.txt LOCALLY' (Chrome/Firefox).\n"
                "Naviguer sur music.youtube.com loggué → exporter pour ce domaine → coller ci-dessous.\n"
                f"Sera enregistré dans: {COOKIES_FILE}",
                id="cookies-help",
            )
            existing = ""
            cp = cookies_path()
            if cp:
                try:
                    existing = cp.read_text()
                except OSError:
                    existing = ""
            yield TextArea(text=existing, id="cookies-area", show_line_numbers=False)
            with Horizontal(id="cookies-buttons"):
                yield Button("Save (Ctrl+S)", id="save", variant="primary")
                yield Button("Cancel (Esc)", id="cancel")
        yield Footer()

    def action_save(self) -> None:
        text = self.query_one("#cookies-area", TextArea).text.strip()
        if not text:
            self.app.notify("Empty input — nothing saved.", severity="warning")
            return
        if not text.startswith("# Netscape") and "youtube" not in text:
            self.app.notify(
                "Doesn't look like a Netscape cookies.txt — saving anyway.",
                severity="warning",
            )
        write_cookies(text + ("\n" if not text.endswith("\n") else ""))
        self.app.notify("Cookies saved — re-validating…", severity="information")
        # Trigger an async re-check so the status bar reflects the new state.
        try:
            self.app.recheck_cookies()  # type: ignore[attr-defined]
        except AttributeError:
            pass
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()
