from __future__ import annotations

import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, Switch

from .. import autostart
from ..config import Config
from ..tray import kill_running_tray, spawn_detached, tray_is_running


class SettingsScreen(ModalScreen[None]):
    """User-facing toggles: auto-start at login, close-to-tray on quit,
    and a live tray-running switch."""

    CSS = """
    SettingsScreen { align: center middle; }
    #dialog {
        width: 90; height: auto;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .section-header {
        height: 1; margin: 1 0 1 0;
        text-style: bold; color: $primary;
    }
    .toggle-row { height: 3; align: left middle; }
    .toggle-row Switch { margin: 0 1 0 0; }
    .toggle-row Label { width: 1fr; padding-top: 1; }
    .info { color: $text-muted; height: auto; min-height: 1; margin: 0 0 1 4; }
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

            # 1) Auto-start at login
            if autostart.is_supported():
                with Horizontal(classes="toggle-row"):
                    yield Switch(value=autostart.is_enabled(), id="autostart")
                    yield Label("Start mixtape at login (background, in the tray)")
                where = (
                    "%APPDATA%\\…\\Startup\\mixtape.lnk" if sys.platform == "win32"
                    else "~/.config/autostart/mixtape.desktop"
                )
                yield Static(f"Drops a launcher at {where}", classes="info")
            else:
                yield Static("[yellow]Auto-start not supported on this platform.[/yellow]", classes="info")

            # 2) Close-to-tray (preference, persisted in config.yaml)
            with Horizontal(classes="toggle-row"):
                yield Switch(value=cfg.close_to_tray, id="close-to-tray")
                yield Label("Close window to system tray (keep running on quit)")
            yield Static(
                "When on, pressing 'q' / Ctrl+C launches the tray and the USB "
                "watcher keeps running. When off, the app fully exits.",
                classes="info",
            )

            # 3) Tray running (live state — flipping it spawns / kills the daemon)
            running = tray_is_running()
            with Horizontal(classes="toggle-row"):
                yield Switch(value=running, id="tray-running")
                yield Label(self._tray_label(running), id="tray-running-label")
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
        return (
            "Tray running [green](active)[/green]" if running
            else "Tray running [dim](stopped)[/dim]"
        )

    def on_switch_changed(self, event: Switch.Changed) -> None:
        sw_id = event.switch.id
        msg_status = self.query_one("#status", Static)
        if sw_id == "autostart":
            ok = autostart.enable() if event.value else autostart.disable()
            if ok:
                msg_status.update(
                    "[green]✓ auto-start enabled — mixtape will launch at login.[/green]"
                    if event.value else
                    "[green]✓ auto-start disabled.[/green]"
                )
            else:
                msg_status.update("[red]✗ couldn't update the autostart entry.[/red]")
                event.switch.value = not event.value
        elif sw_id == "close-to-tray":
            cfg = self._cfg()
            cfg.close_to_tray = bool(event.value)
            cfg.save()
            msg_status.update(
                "[green]✓ closing the window will launch the tray.[/green]"
                if event.value else
                "[green]✓ closing the window will fully exit.[/green]"
            )
        elif sw_id == "tray-running":
            self._toggle_tray(event)

    def _toggle_tray(self, event: Switch.Changed) -> None:
        msg_status = self.query_one("#status", Static)
        sw = event.switch
        if event.value:
            ok, msg = spawn_detached()
            if not ok:
                msg_status.update(f"[red]✗ {msg}[/red]")
                # Use set_reactive so the revert doesn't re-emit Changed
                # and cascade into the OFF-branch (which would call
                # kill_running_tray and could SIGTERM a stale PID).
                sw.set_reactive(Switch.value, False)
                return
            msg_status.update(
                "[yellow]… launching tray (may take a few seconds on cold start)[/yellow]"
            )
            self._tray_wait_deadline = 5.0
            self._tray_wait_elapsed = 0.0
            self.set_timer(0.4, self._poll_tray_started)
        else:
            ok, msg = kill_running_tray()
            self._refresh_tray_label()
            if ok:
                msg_status.update(f"[green]✓ {msg}.[/green]")
            else:
                msg_status.update(f"[yellow]{msg}[/yellow]")

    def _poll_tray_started(self) -> None:
        if tray_is_running():
            self._refresh_tray_label()
            self.query_one("#status", Static).update("[green]✓ tray running.[/green]")
            return
        self._tray_wait_elapsed += 0.4
        if self._tray_wait_elapsed >= self._tray_wait_deadline:
            self._refresh_tray_label()
            from ..config import STATE_DIR
            log_path = STATE_DIR / "tray-spawn.log"
            self.query_one("#status", Static).update(
                f"[red]✗ tray didn't come up within {self._tray_wait_deadline:.0f}s — "
                f"check {log_path} for the error.[/red]"
            )
            return
        self.set_timer(0.4, self._poll_tray_started)

    def _refresh_tray_label(self) -> None:
        running = tray_is_running()
        try:
            sw = self.query_one("#tray-running", Switch)
            if sw.value != running:
                # set_reactive avoids re-firing Switch.Changed — otherwise
                # this cascades back into _toggle_tray and could SIGTERM
                # the wrong process.
                sw.set_reactive(Switch.value, running)
        except Exception:
            pass
        try:
            lbl = self.query_one("#tray-running-label", Label)
            lbl.update(self._tray_label(running))
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
