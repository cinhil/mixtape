"""Settings — autostart at login, close-to-tray, daemon shutdown."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, Switch

from ... import autostart
from ...client import DaemonClient, DaemonError


class SettingsScreen(ModalScreen[bool]):
    """Returns True if anything changed (so the parent can refresh)."""

    CSS = """
    SettingsScreen { align: center middle; }
    #dialog {
        width: 80; height: auto;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .section { height: 1; margin: 1 0 1 0; text-style: bold; color: $primary; }
    .toggle-row { height: 3; align: left middle; }
    .toggle-row Switch { margin: 0 1 0 0; }
    .toggle-row Label { width: 1fr; padding-top: 1; }
    .info { color: $text-muted; height: auto; min-height: 1; margin: 0 0 1 4; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, client: DaemonClient, libraries_snapshot: dict) -> None:
        super().__init__()
        self._client = client
        self._libs = libraries_snapshot
        self._dirty = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Settings[/b]")

            yield Static("── Options ──", classes="section")

            if autostart.is_supported():
                with Horizontal(classes="toggle-row"):
                    yield Switch(value=autostart.is_enabled(), id="autostart")
                    yield Label("Start the mixtape daemon at login")
                where = autostart_target()
                yield Static(f"Drops a launcher at {where}", classes="info")
            else:
                yield Static(
                    "[yellow]Autostart not supported on this platform.[/yellow]",
                    classes="info",
                )

            with Horizontal(classes="toggle-row"):
                yield Switch(
                    value=bool(self._libs.get("close_to_tray")),
                    id="close-to-tray",
                )
                yield Label("Close window to system tray (desktop UI only)")
            yield Static(
                "Affects the PySide6 desktop UI — the TUI doesn't have a tray.",
                classes="info",
            )

            yield Static("── Daemon ──", classes="section")
            with Horizontal():
                yield Button("Shutdown daemon", id="shutdown", variant="warning")
            yield Static(
                "Stops the running daemon. The TUI will exit; relaunch "
                "mixtape to bring it back up (or rely on systemd / "
                "launchd / Windows Startup if configured).",
                classes="info",
            )

            yield Static("", id="status")
            with Horizontal(id="buttons"):
                yield Button("Close (Esc)", id="close")
        yield Footer()

    async def on_switch_changed(self, event: Switch.Changed) -> None:
        sw_id = event.switch.id
        status = self.query_one("#status", Static)
        if sw_id == "autostart":
            ok = autostart.enable() if event.value else autostart.disable()
            if ok:
                self._dirty = True
                status.update(
                    "[green]✓ autostart enabled[/green]" if event.value
                    else "[green]✓ autostart disabled[/green]"
                )
            else:
                status.update("[red]✗ autostart change failed[/red]")
                event.switch.value = not event.value
        elif sw_id == "close-to-tray":
            try:
                await self._client.set_close_to_tray(bool(event.value))
                self._dirty = True
                status.update(
                    "[green]✓ window will close to tray[/green]" if event.value
                    else "[green]✓ window closes will fully exit[/green]"
                )
            except DaemonError as e:
                status.update(f"[red]{e}[/red]")
                event.switch.value = not event.value

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.action_close()
        elif event.button.id == "shutdown":
            try:
                await self._client.shutdown()
            except DaemonError:
                pass
            # Daemon shutdown is loud — close ourselves.
            self.dismiss(True)

    def action_close(self) -> None:
        self.dismiss(self._dirty)


def autostart_target() -> str:
    import sys
    if sys.platform == "win32":
        return "%APPDATA%\\…\\Startup\\mixtape-daemon.lnk"
    if sys.platform == "darwin":
        return "~/Library/LaunchAgents/com.cinhil.mixtape.daemon.plist"
    return "~/.config/autostart/mixtape-daemon.desktop"
