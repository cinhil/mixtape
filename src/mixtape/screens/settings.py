from __future__ import annotations

import shutil
import subprocess
import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static
from ..widgets import Checkbox

from .. import autostart


class SettingsScreen(ModalScreen[None]):
    """User-facing toggles: start at login, launch tray now."""

    CSS = """
    SettingsScreen { align: center middle; }
    #dialog {
        width: 80; height: auto;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .row { height: auto; margin: 0 0 1 0; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    Checkbox { margin: 0 0 1 0; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Settings[/b]")

            # Auto-start
            if autostart.is_supported():
                yield Checkbox(
                    "Start mixtape at login (background, in the system tray)",
                    value=autostart.is_enabled(),
                    id="autostart",
                )
                where = (
                    "%APPDATA%\\…\\Startup\\mixtape.lnk" if sys.platform == "win32"
                    else "~/.config/autostart/mixtape.desktop"
                )
                yield Static(f"[dim]Drops a launcher at {where}[/dim]", id="autostart-info")
            else:
                yield Static("[yellow]Auto-start not supported on this platform.[/yellow]")

            # Tray launch now
            yield Static("[dim]Tray mode runs in the background — USB plug events trigger sync, "
                         "click the icon to open the TUI.[/dim]", id="tray-info")
            with Horizontal(classes="row"):
                yield Button("Launch tray now", id="launch-tray", variant="primary")
                yield Button("Quit and switch to tray", id="switch-tray", variant="warning")

            yield Static("", id="status")
            with Horizontal(id="buttons"):
                yield Button("Close (Esc)", id="close")
        yield Footer()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id != "autostart":
            return
        ok = autostart.enable() if event.value else autostart.disable()
        msg_status = self.query_one("#status", Static)
        if ok:
            msg_status.update(
                "[green]✓ auto-start enabled — mixtape will launch at login.[/green]"
                if event.value else
                "[green]✓ auto-start disabled.[/green]"
            )
        else:
            msg_status.update("[red]✗ couldn't update the autostart entry.[/red]")
            # revert visual state if we failed
            event.checkbox.value = not event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "close":
            self.dismiss(None)
        elif bid == "launch-tray":
            self._launch_tray(detach=True)
        elif bid == "switch-tray":
            self._launch_tray(detach=True)
            self.app.exit()

    def _launch_tray(self, detach: bool = True) -> None:
        exe = shutil.which("mixtape") or sys.executable
        cmd: list[str]
        if exe.endswith("mixtape") or exe.endswith("mixtape.exe"):
            cmd = [exe, "--tray"]
        else:
            cmd = [exe, "-m", "mixtape", "--tray"]
        kwargs: dict = {"start_new_session": True} if detach else {}
        try:
            subprocess.Popen(cmd, **kwargs)
            self.query_one("#status", Static).update("[green]✓ tray launched.[/green]")
        except OSError as e:
            self.query_one("#status", Static).update(f"[red]✗ {e}[/red]")

    def action_close(self) -> None:
        self.dismiss(None)
