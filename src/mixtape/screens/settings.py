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
from ..tray import kill_running_tray, spawn_detached, tray_is_running


class SettingsScreen(ModalScreen[None]):
    """User-facing toggles: start at login, launch tray now."""

    CSS = """
    SettingsScreen { align: center middle; }
    #dialog {
        width: 86; height: auto;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .section-header {
        height: 1; margin: 1 0 1 0;
        text-style: bold; color: $primary;
    }
    .info { color: $text-muted; height: auto; min-height: 1; margin: 0 0 1 2; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        cfg = self._cfg()
        with Vertical(id="dialog"):
            yield Label("[b]Settings[/b]")

            yield Static("── Options ──", classes="section-header")

            # 1) Auto-start
            if autostart.is_supported():
                yield Checkbox(
                    "Start mixtape at login (background, in the tray)",
                    value=autostart.is_enabled(),
                    id="autostart",
                )
                where = (
                    "%APPDATA%\\…\\Startup\\mixtape.lnk" if sys.platform == "win32"
                    else "~/.config/autostart/mixtape.desktop"
                )
                yield Static(f"Drops a launcher at {where}", classes="info")
            else:
                yield Static("[yellow]Auto-start not supported on this platform.[/yellow]", classes="info")

            # 2) Close-to-tray (preference, persisted in config)
            yield Checkbox(
                "Close window to system tray (keep running on quit)",
                value=cfg.close_to_tray,
                id="close-to-tray",
            )
            yield Static(
                "When on, pressing 'q' / Ctrl+C launches the tray and the USB "
                "watcher keeps running. When off, the app fully exits.",
                classes="info",
            )

            # 3) Tray running (live state — flipping it spawns / kills the tray)
            running = tray_is_running()
            yield Checkbox(
                self._tray_label(running),
                value=running,
                id="tray-running",
            )
            yield Static(
                "Spawns or stops the tray daemon right now. The tray runs in the "
                "background, watches USB plug events, and shows a clickable icon.",
                classes="info",
            )

            yield Static("", id="status")
            with Horizontal(id="buttons"):
                yield Button("Close (Esc)", id="close")
        yield Footer()

    def _cfg(self) -> Config:
        cfg = getattr(self.app, "config", None)
        return cfg if isinstance(cfg, Config) else Config.load()

    def _tray_label(self, running: bool) -> str:
        return "Tray running [green](active)[/green]" if running else "Tray running [dim](stopped)[/dim]"

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
        elif cb_id == "tray-running":
            self._toggle_tray(event)

    def _toggle_tray(self, event: Checkbox.Changed) -> None:
        msg_status = self.query_one("#status", Static)
        cb = event.checkbox
        if event.value:
            ok, msg = spawn_detached()
            if ok:
                # Give the new process a moment to write its pid file before
                # we re-query state for the label.
                self.set_timer(0.6, self._refresh_tray_label)
                msg_status.update("[green]✓ tray launched.[/green]")
            else:
                msg_status.update(f"[red]✗ {msg}[/red]")
                cb.value = False  # revert visual
        else:
            ok, msg = kill_running_tray()
            if ok:
                self._refresh_tray_label()
                msg_status.update(f"[green]✓ {msg}.[/green]")
            else:
                msg_status.update(f"[yellow]{msg}[/yellow]")
                # Re-query state in case the user clicked while it was already
                # off — keep the visual aligned with reality.
                self._refresh_tray_label()

    def _refresh_tray_label(self) -> None:
        try:
            cb = self.query_one("#tray-running", Checkbox)
        except Exception:
            return
        running = tray_is_running()
        cb.label = self._tray_label(running)
        if cb.value != running:
            cb.value = running

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
