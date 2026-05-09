from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, LoadingIndicator


class QuittingScreen(ModalScreen[None]):
    """Brief modal shown while the app shuts down."""

    CSS = """
    QuittingScreen { align: center middle; }
    #quit-box {
        width: 40; height: 7;
        border: round $warning; background: $surface;
        padding: 1 2;
        align: center middle;
    }
    #quit-msg { text-align: center; height: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-box"):
            yield Label("[b]Fermeture en cours…[/b]", id="quit-msg")
            yield LoadingIndicator()
