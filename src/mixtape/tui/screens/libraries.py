"""Libraries manager — switch active library, register a USB volume,
add a local folder library, remove a library."""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from ...client import DaemonClient, DaemonError


class LibrariesScreen(ModalScreen[bool]):
    """Returns True if anything changed (so the parent can refresh)."""

    CSS = """
    LibrariesScreen { align: center middle; }
    #dialog {
        width: 100; height: 36;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .section { margin: 1 0 0 0; color: $primary; text-style: bold; }
    .help { color: $text-muted; height: auto; min-height: 1; margin: 0 0 1 0; }
    DataTable { height: 8; }
    .row { height: 3; margin: 0 0 1 0; }
    .row Input { width: 1fr; }
    .label { width: 14; padding-top: 1; color: $text-muted; }
    #status { color: $text-muted; height: auto; min-height: 1; margin: 1 0; }
    #buttons { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, client: DaemonClient) -> None:
        super().__init__()
        self._client = client
        self._libraries: list[dict[str, Any]] = []
        self._volumes: list[dict[str, Any]] = []
        self._active: str = ""
        self._dirty = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Libraries[/b]")

            yield Static("── Registered libraries ──", classes="section")
            yield Static(
                "Press Enter (or 'a') on a row to set it active. 'r' to remove.",
                classes="help",
            )
            yield DataTable(id="libs", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="lib-buttons"):
                yield Button("Set active", id="set_active", variant="primary")
                yield Button("Remove", id="remove", variant="error")
                yield Button("Refresh", id="refresh")

            yield Static("── Detected volumes ──", classes="section")
            yield Static(
                "USB drives currently plugged in. Select a row, then 'Register' "
                "to add it (creating a .mixtape marker if missing).",
                classes="help",
            )
            yield DataTable(id="vols", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="vol-buttons"):
                yield Button("Register selected volume", id="register_vol", variant="primary")

            yield Static("── Add a local-folder library ──", classes="section")
            with Horizontal(classes="row"):
                yield Static("Name", classes="label")
                yield Input(id="local_name", placeholder="e.g. PC, Backup, Music")
            with Horizontal(classes="row"):
                yield Static("Path", classes="label")
                yield Input(id="local_path", placeholder="/path/to/folder")
            with Horizontal():
                yield Button("Add local library", id="add_local")

            yield Static("", id="status")
            with Horizontal(id="buttons"):
                yield Button("Close (Esc)", id="close")
        yield Footer()

    def on_mount(self) -> None:
        libs = self.query_one("#libs", DataTable)
        libs.add_columns("Active", "Name", "Online", "Path", "UUID")
        vols = self.query_one("#vols", DataTable)
        vols.add_columns("Mount", "Label", "FS", "Removable", "Marker")
        self.run_worker(self._reload(), exclusive=True, group="libs")

    async def _reload(self) -> None:
        status = self.query_one("#status", Static)
        try:
            snap = await self._client.libraries()
            self._libraries = snap.get("libraries", []) or []
            self._active = snap.get("active", "")
            self._volumes = await self._client.list_volumes()
        except DaemonError as e:
            status.update(f"[red]{e}[/red]")
            return
        libs = self.query_one("#libs", DataTable)
        libs.clear()
        for lib in self._libraries:
            from pathlib import Path
            online = Path(str(lib.get("path", ""))).expanduser().is_dir()
            libs.add_row(
                "★" if lib.get("name") == self._active else "",
                str(lib.get("name", "?")),
                "✓" if online else "—",
                str(lib.get("path", "")),
                str(lib.get("uuid", ""))[:8] + ("…" if len(str(lib.get("uuid", ""))) > 8 else ""),
                key=str(lib.get("name")),
            )
        vols = self.query_one("#vols", DataTable)
        vols.clear()
        for v in self._volumes:
            vols.add_row(
                str(v.get("mount_path", "")),
                str(v.get("label") or ""),
                str(v.get("fs_type") or ""),
                "✓" if v.get("is_removable") else "—",
                "✓" if v.get("marker") else "—",
                key=str(v.get("mount_path")),
            )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "close":
            self.action_close()
        elif bid == "refresh":
            await self._reload()
        elif bid == "set_active":
            await self._set_active_selected()
        elif bid == "remove":
            await self._remove_selected()
        elif bid == "register_vol":
            await self._register_vol_selected()
        elif bid == "add_local":
            await self._add_local()

    def action_close(self) -> None:
        self.dismiss(self._dirty)

    def _selected_lib_name(self) -> str | None:
        table = self.query_one("#libs", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        return None if row_key.value is None else str(row_key.value)

    def _selected_vol_path(self) -> str | None:
        table = self.query_one("#vols", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        return None if row_key.value is None else str(row_key.value)

    async def _set_active_selected(self) -> None:
        name = self._selected_lib_name()
        status = self.query_one("#status", Static)
        if not name:
            status.update("[yellow]Pick a library row first.[/yellow]")
            return
        try:
            await self._client.set_active_library(name)
        except DaemonError as e:
            status.update(f"[red]{e}[/red]")
            return
        self._dirty = True
        status.update(f"[green]✓ '{name}' is now active[/green]")
        await self._reload()

    async def _remove_selected(self) -> None:
        name = self._selected_lib_name()
        status = self.query_one("#status", Static)
        if not name:
            status.update("[yellow]Pick a library row first.[/yellow]")
            return
        try:
            await self._client.remove_library(name)
        except DaemonError as e:
            status.update(f"[red]{e}[/red]")
            return
        self._dirty = True
        status.update(f"[green]✓ removed '{name}' (audio files left in place)[/green]")
        await self._reload()

    async def _register_vol_selected(self) -> None:
        mount = self._selected_vol_path()
        status = self.query_one("#status", Static)
        if not mount:
            status.update("[yellow]Pick a volume row first.[/yellow]")
            return
        try:
            res = await self._client.register_volume(mount)
        except DaemonError as e:
            status.update(f"[red]{e}[/red]")
            return
        self._dirty = True
        verb = "registered" if res.get("created") else "linked"
        status.update(f"[green]✓ {verb} '{res.get('name')}' on {mount}[/green]")
        await self._reload()

    async def _add_local(self) -> None:
        name = self.query_one("#local_name", Input).value.strip()
        path = self.query_one("#local_path", Input).value.strip()
        status = self.query_one("#status", Static)
        if not name or not path:
            status.update("[yellow]Both Name and Path are required.[/yellow]")
            return
        try:
            await self._client.add_library(name=name, path=path, create_marker=True)
        except DaemonError as e:
            status.update(f"[red]{e}[/red]")
            return
        self._dirty = True
        status.update(f"[green]✓ added '{name}' (marker written)[/green]")
        self.query_one("#local_name", Input).value = ""
        self.query_one("#local_path", Input).value = ""
        await self._reload()
