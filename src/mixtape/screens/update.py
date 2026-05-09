"""Modal that shows mixtape's update status and applies it on demand.

Dev channel: runs ``git pull --ff-only`` in the repo dir.
Stable channel: shows the install command and copies it to the clipboard
(running an installer that overwrites the current process from inside the
process is fragile, so we point the user at a fresh shell instead).
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static

from ..update_check import UpdateStatus, get_update_status, invalidate_cache


def _repo_dir() -> Path | None:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / ".git").exists():
            return ancestor
    return None


def _install_cmd(platform: str, dev: bool) -> str:
    if platform == "windows":
        base = "irm https://raw.githubusercontent.com/cinhil/mixtape/main/install.ps1 | iex"
        return f"{base} -- --dev" if dev else base
    base = "curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash"
    return f"{base} -s -- --dev" if dev else base


class UpdateScreen(ModalScreen[None]):
    CSS = """
    UpdateScreen { align: center middle; }
    #dialog {
        width: 86; height: auto;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    #title { height: 1; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    #log {
        height: auto; max-height: 12;
        color: $text-muted;
        border: round $panel; padding: 0 1; margin-top: 1;
    }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._busy = False

    def compose(self) -> ComposeResult:
        # We always do a fresh check on open (cache may be hours old or
        # stale after a `git pull`); the summary starts as "checking" and
        # gets replaced when on_mount's worker returns.
        with Vertical(id="dialog"):
            yield Label("[b]Mixtape update[/b]", id="title")
            yield Static("[yellow]… checking for updates[/yellow]", id="summary")
            yield Static("", id="status")
            yield Static("", id="log")
            with Horizontal(id="buttons"):
                # Apply button starts hidden; the check result reveals it
                # if there's something to apply.
                apply_btn = Button(self._apply_label(None), id="apply", variant="primary")
                apply_btn.display = False
                yield apply_btn
                yield Button("Close (Esc)", id="close")
        yield Footer()

    def on_mount(self) -> None:
        self._do_recheck()

    def _apply_label(self, status: UpdateStatus | None) -> str:
        if status and status.channel == "stable":
            return "Copy install command"
        return "Pull latest commits"

    def _render_summary(self, status: UpdateStatus | None) -> str:
        if status is None:
            return "[yellow]Not running from a git checkout — can't determine update status.[/yellow]"
        if not status.has_update:
            return f"[green]✓ {status.message}[/green]"
        return f"[b yellow]↑ {status.message}[/b yellow]\n[dim]channel: {status.channel}[/dim]"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy:
            return
        bid = event.button.id
        if bid == "close":
            self.dismiss(None)
        elif bid == "apply":
            self._do_apply()

    def action_close(self) -> None:
        if not self._busy:
            self.dismiss(None)

    def _set_status(self, markup: str) -> None:
        self.query_one("#status", Static).update(markup)

    def _set_log(self, text: str) -> None:
        self.query_one("#log", Static).update(text or "")

    def _do_recheck(self) -> None:
        # Force a fresh check (no cache) — the modal triggers this on open
        # so the user always sees current state without an extra click.
        invalidate_cache()
        self._set_status("")

        def worker() -> None:
            status = get_update_status(force=True)
            self.app.call_from_thread(self._after_recheck, status)

        self._busy = True
        threading.Thread(target=worker, daemon=True, name="update-check").start()

    def _after_recheck(self, status: UpdateStatus | None) -> None:
        self._busy = False
        self.query_one("#summary", Static).update(self._render_summary(status))
        self._set_status("")
        # Toggle the always-mounted apply button to match the new status.
        try:
            apply_btn = self.query_one("#apply", Button)
            apply_btn.label = self._apply_label(status)
            apply_btn.display = bool(status and status.has_update)
        except Exception:
            pass
        # Also refresh the parent screen's banner.
        try:
            self.app.update_status = status  # type: ignore[attr-defined,assignment]
            for s in self.app.screen_stack:
                refresh = getattr(s, "_refresh_status", None)
                if callable(refresh):
                    refresh()
        except Exception:
            pass

    def _do_apply(self) -> None:
        status = get_update_status()
        if not status or not status.has_update:
            return
        if status.channel == "dev":
            self._apply_dev()
        else:
            self._apply_stable()

    def _apply_dev(self) -> None:
        repo = _repo_dir()
        if not repo:
            self._set_status("[red]✗ no .git ancestor — can't pull.[/red]")
            return
        self._busy = True
        self._set_status("[yellow]… running git pull[/yellow]")

        def worker() -> None:
            try:
                proc = subprocess.run(
                    ["git", "-C", str(repo), "pull", "--ff-only"],
                    capture_output=True, text=True, timeout=60,
                )
                ok = proc.returncode == 0
                output = (proc.stdout + proc.stderr).strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                ok = False
                output = str(e)
            self.app.call_from_thread(self._after_pull, ok, output)

        threading.Thread(target=worker, daemon=True, name="git-pull").start()

    def _after_pull(self, ok: bool, output: str) -> None:
        self._busy = False
        self._set_log(output)
        if ok:
            self._set_status(
                "[green]✓ updated — closing mixtape (and the tray if running) "
                "so the new version takes effect…[/green]"
            )
            invalidate_cache()
            # The running Python process still has the *old* modules in
            # memory — the only way to actually pick up the new code is to
            # restart. Stop the tray daemon first so it picks up the new
            # code when the user relaunches; then exit.
            self.set_timer(1.8, self._post_update_shutdown)
        else:
            self._set_status("[red]✗ git pull failed (see log below)[/red]")

    def _post_update_shutdown(self) -> None:
        from ..tray import kill_running_tray, tray_is_running
        if tray_is_running():
            try:
                kill_running_tray()
            except Exception:
                pass
        try:
            self.app.exit()
        except Exception:
            pass

    def _apply_stable(self) -> None:
        platform = getattr(self.app, "platform", "")
        cmd = _install_cmd(platform, dev=False)
        try:
            self.app.copy_to_clipboard(cmd)
            self._set_status(
                "[green]✓ install command copied to clipboard.[/green]\n"
                "[dim]Paste it in a fresh terminal, then restart mixtape.[/dim]"
            )
        except Exception:
            self._set_status(
                "[yellow]Clipboard unavailable. Copy this command manually:[/yellow]"
            )
        self._set_log(cmd)
