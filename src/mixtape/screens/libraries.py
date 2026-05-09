from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from ..config import Config
from .device_setup import DeviceSetupScreen


class LibrariesScreen(Screen):
    """Manage music libraries: PC, USB devices, …  Active determines where syncs go."""

    CSS = """
    Screen { background: $background; }
    #status-bar { height: 1; padding: 0 1; color: $text-muted; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("enter", "activate", "Set active"),
        Binding("u", "register_usb", "Register USB"),
        Binding("a", "add_manual", "Add path"),
        Binding("d", "delete", "Delete"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static(
                "[b]Libraries[/b]  —  Enter: set active  |  u: register USB device  |  a: add path  |  d: delete  |  Esc: back",
                id="status-bar",
            )
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Libraries"
        table = self.query_one(DataTable)
        table.add_columns("●", "Name", "Path", "Volume", "Auto-sync", "Status")
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for i, lib in enumerate(self.config.libraries):
            active = "[b green]✓[/b green]" if lib.name == self.config.active_library else " "
            mounted = Path(lib.path).expanduser().exists()
            status = "[green]online[/green]" if mounted else "[yellow]offline[/yellow]"
            auto = "[cyan]yes[/cyan]" if lib.auto_sync else "no"
            table.add_row(
                active, lib.name, lib.path, lib.volume_name or "—", auto, status, key=str(i),
            )

    def _selected_index(self) -> int | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        if row_key.value is None:
            return None
        try:
            return int(row_key.value)
        except (ValueError, TypeError):
            return None

    def action_activate(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.notify("Nothing selected.", severity="warning")
            return
        lib = self.config.libraries[idx]
        if not Path(lib.path).expanduser().exists():
            self.notify(f"Library '{lib.name}' is offline ({lib.path} not mounted).", severity="warning")
            return
        self.config.set_active_library(lib.name)
        self._refresh()
        self.notify(f"Active library: '{lib.name}'.")

    def action_register_usb(self) -> None:
        def cb(result):
            if result is not None:
                self._refresh()
        self.app.push_screen(DeviceSetupScreen(self.config), cb)

    def action_add_manual(self) -> None:
        # Simple inline add via DeviceSetupScreen with manual mode
        def cb(result):
            if result is not None:
                self._refresh()
        self.app.push_screen(DeviceSetupScreen(self.config, manual_mode=True), cb)

    def action_delete(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        lib = self.config.libraries[idx]
        if len(self.config.libraries) <= 1:
            self.notify("Can't delete the only library.", severity="warning")
            return
        self.config.remove_library(lib.name)
        self._refresh()
        self.notify(f"Removed library '{lib.name}'. Files on disk are untouched.")

    def action_back(self) -> None:
        self.app.pop_screen()
