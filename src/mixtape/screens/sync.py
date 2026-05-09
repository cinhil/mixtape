from __future__ import annotations

import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, ProgressBar, RichLog, Static

from ..config import Config, Playlist
from ..downloader import ProgressEvent, sync_playlist
from ..platform_io import flush_filesystem


_MARKUP_RE = re.compile(r"\[/?[a-zA-Z0-9_# ]+\]")


def _strip_markup(s: str) -> str:
    return _MARKUP_RE.sub("", s)


class SyncScreen(ModalScreen[bool]):
    """Run sync for a list of playlists, with per-playlist progress + log."""

    CSS = """
    SyncScreen { align: center middle; }
    #dialog {
        width: 95%; height: 95%;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .pl-row { height: 4; margin: 0 0 1 0; border: round $panel; padding: 0 1; }
    .pl-name { height: 1; }
    .pl-status { height: 1; color: $text-muted; }
    .pl-bar { height: 1; }
    #log { height: 1fr; border: round $panel; }
    #buttons { height: 3; align: center middle; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "close_or_cancel", "Close/Cancel"),
        Binding("ctrl+c", "cancel", "Cancel", show=False, priority=True),
        Binding("y", "copy_log", "Copy log"),
        Binding("p", "show_log_path", "Log path"),
    ]

    def __init__(self, config: Config, playlists: list[tuple[int, Playlist]]) -> None:
        """playlists: list of (index_in_config, playlist)."""
        super().__init__()
        self.config = config
        self.targets = playlists
        self._done = False
        self._cancel = threading.Event()
        active_lib = config.active_library_obj()
        log_root = Path(active_lib.path).expanduser()
        log_root.mkdir(parents=True, exist_ok=True)
        self._log_path = log_root / "sync.log"
        self._log_fp = self._log_path.open("a", encoding="utf-8")
        # Remember where this sync section starts so the "copy" action can
        # extract only the current run (not the whole accumulated file).
        self._log_section_start = self._log_fp.tell()
        self._log_fp.write(
            f"\n{'=' * 60}\n[{datetime.now().isoformat(timespec='seconds')}] Sync start "
            f"→ library {active_lib.name!r} ({active_lib.path})\n"
        )
        for _, pl in self.targets:
            self._log_fp.write(
                f"  - {pl.name} ({pl.format}/{pl.quality}) → {pl.expanded_dir_for(active_lib)}\n"
            )
        self._log_fp.flush()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Sync en cours[/b]")
            with VerticalScroll(id="rows"):
                for i, (_, pl) in enumerate(self.targets):
                    with Vertical(classes="pl-row", id=f"row-{i}"):
                        yield Static(f"[b]{pl.name}[/b]  [dim]({pl.format})[/dim]", classes="pl-name", id=f"name-{i}")
                        yield Static("Pending…", classes="pl-status", id=f"status-{i}")
                        yield ProgressBar(total=100, show_eta=False, classes="pl-bar", id=f"bar-{i}")
            yield RichLog(id="log", highlight=True, markup=True, max_lines=500)
            with Horizontal(id="buttons"):
                yield Button("Cancel (Esc)", id="cancel", variant="warning")
                yield Button("Close", id="close", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._run_all()

    @work(thread=True, exclusive=True)
    def _run_all(self) -> None:
        library = self.config.active_library_obj()
        for ui_idx, (cfg_idx, pl) in enumerate(self.targets):
            if self._cancel.is_set():
                self.app.call_from_thread(self._log, f"[yellow]Skipped[/yellow] {pl.name} (cancelled)")
                continue
            try:
                count = sync_playlist(pl, library, ui_idx, self._post, cancel=self._cancel)
                self.app.call_from_thread(self._mark_done, cfg_idx, count)
            except Exception as e:  # noqa: BLE001
                self.app.call_from_thread(self._log, f"[red]ERROR[/red] {pl.name}: {e}")
        # Flush kernel buffers so the device is physically up-to-date — safe to
        # unplug as soon as the user sees the "all done" notification.
        try:
            flush_filesystem()
        except Exception:  # noqa: BLE001
            pass
        self.app.call_from_thread(self._all_done)

    def _post(self, ev: ProgressEvent) -> None:
        self.app.call_from_thread(self._handle_event, ev)

    def _handle_event(self, ev: ProgressEvent) -> None:
        i = ev.playlist_idx
        try:
            status = self.query_one(f"#status-{i}", Static)
            bar = self.query_one(f"#bar-{i}", ProgressBar)
        except Exception:
            return
        src = f" [dim]\\[{ev.source}][/dim]" if ev.source else ""
        if ev.kind == "start":
            status.update(f"[cyan]Starting[/cyan] — {ev.track_total} tracks total")
            bar.update(total=max(ev.track_total, 1), progress=0)
            self._log(f"[cyan]▶[/cyan] {ev.message}")
        elif ev.kind == "source":
            # Source info shows in status bar only; we'll log a single line on `finished`.
            status.update(f"[{ev.track_idx}/{ev.track_total}]{src} {ev.track_title}")
        elif ev.kind == "progress":
            status.update(f"[{ev.track_idx}/{ev.track_total}]{src} {ev.track_title}  ({ev.percent:5.1f}%)")
            bar.update(progress=max(ev.track_idx - 1, 0) + ev.percent / 100.0)
        elif ev.kind == "finished":
            status.update(f"[{ev.track_idx}/{ev.track_total}]{src} [green]✓[/green] {ev.track_title}")
            bar.update(progress=ev.track_idx)
            suffix = f" [dim]— {ev.source}[/dim]" if ev.source else ""
            num_str = f"[b]{ev.track_number:03d}[/b] " if ev.track_number else ""
            self._log(f"  [green]✓[/green] {num_str}{ev.track_title}  [dim]\\[{ev.track_idx}/{ev.track_total}][/dim]{suffix}")
        elif ev.kind == "log":
            self._log(f"  [dim]{ev.message}[/dim]")
        elif ev.kind == "done":
            status.update(f"[green]Done[/green] — {ev.track_total} tracks")
            bar.update(progress=ev.track_total)
            self._log(f"[green]✔[/green] {ev.message}")
        elif ev.kind == "cancelled":
            status.update(f"[yellow]Cancelled[/yellow] — {ev.message}")
            self._log(f"[yellow]⏹[/yellow] {ev.message}")
        elif ev.kind == "error":
            status.update(f"[red]Error[/red] — {ev.message}")
            self._log(f"[red]✗[/red] {ev.message}")

    def _log(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)
        try:
            self._log_fp.write(f"[{datetime.now().strftime('%H:%M:%S')}] {_strip_markup(msg)}\n")
            self._log_fp.flush()
        except Exception:
            pass

    def action_show_log_path(self) -> None:
        self.app.notify(f"Log: {self._log_path}", timeout=10)
        self._log(f"[dim]Log file: {self._log_path}[/dim]")

    def action_copy_log(self) -> None:
        """Copy the current sync section to clipboard. Uses UTF-16 LE for clip.exe
        so emojis and Unicode arrows aren't mangled by Windows code page handling."""
        try:
            self._log_fp.flush()
            with self._log_path.open("r", encoding="utf-8") as f:
                f.seek(self._log_section_start)
                text = f.read()
        except OSError as e:
            self.app.notify(f"Cannot read log: {e}", severity="error")
            return
        if not text.strip():
            self.app.notify("Nothing to copy yet.", severity="warning")
            return

        # clip.exe expects UTF-16 LE (with BOM for safety). Linux clipboard
        # tools take UTF-8 directly.
        for cmd, encoding in (
            (["clip.exe"], "utf-16-le-bom"),
            (["wl-copy"], "utf-8"),
            (["xclip", "-selection", "clipboard"], "utf-8"),
        ):
            data = ("﻿" + text).encode("utf-16-le") if encoding == "utf-16-le-bom" else text.encode("utf-8")
            try:
                subprocess.run(cmd, input=data, check=True, timeout=5)
                self.app.notify(
                    f"Current sync log copied to clipboard via {cmd[0]} ({len(text)} chars).",
                    severity="information",
                )
                return
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
        self.app.notify(
            f"No clipboard tool found (tried clip.exe, wl-copy, xclip). Log file: {self._log_path}",
            severity="warning",
            timeout=10,
        )

    def _mark_done(self, cfg_idx: int, count: int) -> None:
        self.config.mark_synced(cfg_idx, count)

    def _all_done(self) -> None:
        self._done = True
        self.query_one("#close", Button).disabled = False
        self.query_one("#cancel", Button).disabled = True
        if self._cancel.is_set():
            self._log("[b yellow]Sync interrupted by user.[/b yellow]")
            self.app.notify("Sync cancelled.", severity="warning")
        else:
            self._log("[b green]All sync tasks complete.[/b green]")
            # If syncing to a removable library, advertise safe-unplug since
            # we already flushed the filesystem before this hook fired.
            active_lib = self.config.active_library_obj()
            looks_removable = (
                bool(active_lib.volume_name)
                or str(active_lib.path).startswith("/mnt/")
                or str(active_lib.path).startswith("/media/")
                or str(active_lib.path).startswith("/run/media/")
            )
            if looks_removable:
                self._log("[b green]✓ Filesystem flushed — safe to unplug now.[/b green]")
                self.app.notify(
                    f"Sync done — '{active_lib.name}' is safe to unplug.",
                    severity="information", timeout=10,
                )
            else:
                self.app.notify("Sync finished.", severity="information")
        self._log(f"[dim]Log saved to {self._log_path} — press 'y' to copy to clipboard.[/dim]")
        try:
            self._log_fp.flush()
        except Exception:
            pass

    def on_unmount(self) -> None:
        try:
            self._log_fp.close()
        except Exception:
            pass

    def action_cancel(self) -> None:
        if self._done:
            return
        if self._cancel.is_set():
            self.app.notify("Already cancelling…", severity="warning")
            return
        self._cancel.set()
        self.query_one("#cancel", Button).disabled = True
        self.query_one("#cancel", Button).label = "Cancelling…"
        self._log("[yellow]⏹ Cancel requested — finishing current track and stopping…[/yellow]")
        self.app.notify("Cancel requested.", severity="warning")

    def action_close_or_cancel(self) -> None:
        if self._done:
            self.dismiss(True)
        else:
            self.action_cancel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
        elif event.button.id == "close":
            if self._done:
                self.dismiss(True)
