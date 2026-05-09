"""Mixtape update modal — auto-checks on open, applies via the daemon."""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static

from ...client import DaemonClient, DaemonError


class UpdateScreen(ModalScreen[bool]):
    CSS = """
    UpdateScreen { align: center middle; }
    #dialog {
        width: 86; height: auto;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    #title { height: 1; }
    #summary { height: auto; min-height: 2; margin: 1 0; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    #log {
        height: auto; max-height: 12;
        color: $text-muted;
        border: round $panel; padding: 0 1; margin-top: 1;
    }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, client: DaemonClient) -> None:
        super().__init__()
        self._client = client
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Mixtape update[/b]", id="title")
            yield Static("[yellow]… checking for updates[/yellow]", id="summary")
            yield Static("", id="status")
            yield Static("", id="log")
            with Horizontal(id="buttons"):
                apply_btn = Button("Apply", id="apply", variant="primary")
                apply_btn.display = False
                yield apply_btn
                yield Button("Close (Esc)", id="close")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._check(), exclusive=True, group="update")

    async def _check(self) -> None:
        try:
            await self._client.refresh_update()
            s = await self._client.status()
        except DaemonError as e:
            self.query_one("#summary", Static).update(f"[red]{e}[/red]")
            return
        upd: dict[str, Any] | None = s.get("update")
        summary = self.query_one("#summary", Static)
        apply_btn = self.query_one("#apply", Button)
        if upd is None:
            summary.update("[yellow]Not running from a git checkout — can't determine update status.[/yellow]")
            apply_btn.display = False
            return
        if upd.get("behind"):
            summary.update(
                f"[b yellow]↑ {upd.get('message','update available')}[/b yellow]\n"
                f"[dim]channel: {upd.get('channel','?')}[/dim]"
            )
            apply_btn.display = True
            apply_btn.label = (
                "Pull latest commits" if upd.get("channel") == "dev"
                else "Show install command"
            )
        else:
            summary.update(f"[green]✓ {upd.get('message','up to date')}[/green]")
            apply_btn.display = False

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy:
            return
        if event.button.id == "close":
            self.action_close()
        elif event.button.id == "apply":
            await self._apply()

    def action_close(self) -> None:
        if not self._busy:
            self.dismiss(False)

    async def _apply(self) -> None:
        self._busy = True
        self.query_one("#status", Static).update("[yellow]… running git pull[/yellow]")
        try:
            res = await self._client.apply_update()
        except DaemonError as e:
            self.query_one("#status", Static).update(f"[red]✗ {e}[/red]")
            self._busy = False
            return
        self.query_one("#log", Static).update(str(res.get("message", "")))
        if res.get("ok"):
            self.query_one("#status", Static).update(
                "[green]✓ updated — close mixtape and relaunch to use the new code.[/green]"
            )
        else:
            self.query_one("#status", Static).update("[red]✗ update failed (see log)[/red]")
        self._busy = False
