from __future__ import annotations

import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static
from ..widgets import Checkbox

from .. import autostart
from ..config import Config
from ..tray import spawn_detached


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
        cfg = self._cfg()
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

            # Close-to-tray
            yield Checkbox(
                "Close window to system tray (keep running in background)",
                value=cfg.close_to_tray,
                id="close-to-tray",
            )
            yield Static(
                "[dim]When on, pressing 'q' / Ctrl+C launches the tray and the "
                "USB watcher keeps running; when off, the app fully exits.[/dim]",
                id="close-to-tray-info",
            )

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

    def _cfg(self) -> Config:
        cfg = getattr(self.app, "config", None)
        return cfg if isinstance(cfg, Config) else Config.load()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        cb_id = event.checkbox.id
        msg_status = self.query_one("#status", Static)
        if cb_id == "autostart":
            ok = autostart.enable() if event.value else autostart.disable()
            if ok:
                msg_status.update(
                    "[green]✓ auto-start enabled — mixtape will launch at login.[/green]"
                    if event.value else
                    "[green]✓ auto-start disabled.[/green]"
                )
            else:
                msg_status.update("[red]✗ couldn't update the autostart entry.[/red]")
                event.checkbox.value = not event.value
        elif cb_id == "close-to-tray":
            cfg = self._cfg()
            cfg.close_to_tray = bool(event.value)
            cfg.save()
            msg_status.update(
                "[green]✓ closing the window will launch the tray.[/green]"
                if event.value else
                "[green]✓ closing the window will fully exit.[/green]"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "close":
            self.dismiss(None)
        elif bid == "launch-tray":
            self._launch_tray()
        elif bid == "switch-tray":
            self._launch_tray()
            self.app.exit()

    def _launch_tray(self) -> None:
        ok, msg = spawn_detached()
        if ok:
            self.query_one("#status", Static).update("[green]✓ tray launched.[/green]")
        else:
            self.query_one("#status", Static).update(f"[red]✗ {msg}[/red]")

    def action_close(self) -> None:
        self.dismiss(None)
