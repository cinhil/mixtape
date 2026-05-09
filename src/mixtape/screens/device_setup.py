from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Input, Label, ListItem, ListView, Select, Static

from ..config import Config, Library, Playlist
from ..library_marker import (
    LibraryMarker, discover_playlists, read_marker, write_marker,
)
from ..platform_io import Volume, detect_backend


class DeviceSetupScreen(ModalScreen[Library | None]):
    """Two-step wizard: pick a drive (or enter a path), then pick the library
    root folder (where playlist subdirs live, e.g. ``D:\\music``)."""

    CSS = """
    DeviceSetupScreen { align: center middle; }
    #dialog {
        width: 90; height: 90%;
        border: round $primary; background: $surface;
        padding: 1 2;
    }
    .row { height: auto; margin: 0 0 1 0; }
    .label { width: 16; }
    Input, Select { width: 1fr; }
    #folder-list { height: 1fr; border: round $panel; }
    #buttons { height: 3; align: center middle; }
    Button { margin: 0 1; }
    #status { color: $text-muted; height: auto; min-height: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, config: Config, manual_mode: bool = False) -> None:
        super().__init__()
        self.config = config
        self.manual_mode = manual_mode
        self._selected_volume: Volume | None = None
        self._current_browse: Path | None = None
        self._backend = detect_backend()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Register a music library[/b]")
            if not self.manual_mode:
                with Horizontal(classes="row"):
                    yield Label("Drive", classes="label")
                    drives = self._available_drives()
                    yield Select(
                        drives,
                        value=drives[0][1] if drives else Select.BLANK,
                        id="drive",
                        allow_blank=True,
                        prompt="(pick drive or enter path manually below)",
                    )
            with Horizontal(classes="row"):
                yield Label("Library root", classes="label")
                yield Input(
                    placeholder="/mnt/d/music — folder that contains one subdir per playlist",
                    id="root",
                )
            yield Static("", id="status")
            yield Label("[dim]Browse subfolders (double-Enter on the right one):[/dim]")
            yield ListView(id="folder-list")
            with Horizontal(classes="row"):
                yield Label("Name", classes="label")
                yield Input(placeholder="e.g. USB MP3 Player", id="name")
            with Horizontal(classes="row"):
                yield Checkbox("Auto-sync when this device is plugged in", value=True, id="auto_sync")
            with Horizontal(id="buttons"):
                yield Button("Save (Ctrl+S)", id="save", variant="success")
                yield Button("Cancel (Esc)", id="cancel")
        yield Footer()

    def _available_drives(self) -> list[tuple[str, str]]:
        opts = []
        for v in self._backend.list_volumes():
            label = (
                f"{v.identifier}: {v.label or '(no label)'} — "
                f"{v.size_bytes/1e9:.1f}GB {v.fs_type}"
                + (" [removable]" if v.is_removable else "")
            )
            opts.append((label, str(v.mount_path)))
        return opts

    def on_mount(self) -> None:
        if self.manual_mode:
            self.query_one("#root", Input).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "drive":
            return
        if event.value is Select.BLANK:
            return
        # Pre-fill the root input with the chosen drive
        self.query_one("#root", Input).value = str(event.value)
        self._refresh_browse(Path(str(event.value)))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "root":
            return
        path = Path(event.value).expanduser()
        if path.exists() and path.is_dir():
            self._refresh_browse(path)

    def _refresh_browse(self, path: Path) -> None:
        self._current_browse = path
        listview = self.query_one("#folder-list", ListView)
        listview.clear()
        try:
            entries = sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError as e:
            self.query_one("#status", Static).update(f"[red]Cannot list {path}: {e}[/red]")
            return
        if path.parent != path:
            listview.append(ListItem(Static("[..] (parent)")))
        for sub in entries:
            listview.append(ListItem(Static(f"[cyan]{sub.name}/[/cyan]")))
        self.query_one("#status", Static).update(
            f"Browsing: [cyan]{path}[/cyan]  ({len(entries)} subfolders)"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not self._current_browse:
            return
        # Determine which entry was clicked
        idx = self.query_one("#folder-list", ListView).index
        if idx is None:
            return
        path = self._current_browse
        try:
            entries = sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            return
        # Account for the "[..]" parent entry at index 0
        offset = 0
        if path.parent != path:
            if idx == 0:
                # Go up
                self.query_one("#root", Input).value = str(path.parent)
                self._refresh_browse(path.parent)
                return
            offset = 1
        real_idx = idx - offset
        if 0 <= real_idx < len(entries):
            target = entries[real_idx]
            self.query_one("#root", Input).value = str(target)
            self._refresh_browse(target)

    def action_save(self) -> None:
        root_str = self.query_one("#root", Input).value.strip()
        name = self.query_one("#name", Input).value.strip()
        auto_sync = self.query_one("#auto_sync", Checkbox).value
        if not root_str or not name:
            self.app.notify("Path and name are required.", severity="error")
            return
        root = Path(root_str).expanduser()
        if not root.exists():
            self.app.notify(f"Path doesn't exist: {root}", severity="warning")

        # Detect the volume label (kept as a fallback hint; primary identity = uuid)
        volume_name = ""
        for v in self._backend.list_volumes():
            if root_str.startswith(str(v.mount_path)):
                volume_name = v.label
                break

        # If a .mixtape marker is already at this root (because the device was
        # registered on another machine before), reuse its uuid + name instead
        # of generating new ones — that way both machines see the same library.
        existing = read_marker(root) if root.is_dir() else None
        if existing:
            uid = existing.uuid
            name = name or existing.name
        else:
            marker = LibraryMarker.new(name=name, auto_sync=bool(auto_sync), mixtape_version="0.1.0b1")
            uid = marker.uuid
            try:
                write_marker(root, marker)
            except OSError as e:
                self.app.notify(f"Could not write .mixtape marker: {e}", severity="warning")

        try:
            self.config.add_library(Library(
                name=name, path=str(root), volume_name=volume_name,
                auto_sync=bool(auto_sync), uuid=uid,
            ))
        except ValueError as e:
            self.app.notify(str(e), severity="error")
            return

        # Auto-import any playlists already present on the library (read from
        # each subdir's .manifest.yaml). De-duped by URL against what's in the
        # central config — a playlist already known on this machine is never
        # added twice.
        imported = 0
        if root.is_dir():
            known_urls = {p.url for p in self.config.playlists}
            for entry in discover_playlists(root):
                if entry["url"] in known_urls:
                    continue
                self.config.playlists.append(Playlist(
                    name=entry["name"],
                    url=entry["url"],
                    format=entry["format"],
                    quality=entry["quality"],
                    relative_path=entry["relative_path"],
                    requires_cookies=entry["requires_cookies"],
                    track_count=entry.get("track_count", 0),
                ))
                known_urls.add(entry["url"])
                imported += 1
            if imported:
                self.config.save()

        msg = f"Library '{name}' registered (uuid: {uid[:8]}…)"
        if imported:
            msg += f" — imported {imported} playlist(s) from .mixtape device."
        self.app.notify(msg, timeout=8)
        self.dismiss(self.config.get_library(name))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()
