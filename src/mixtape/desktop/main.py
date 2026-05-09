"""Mixtape desktop UI — PySide6 + qasync.

Architecture
------------
- One QApplication, one asyncio loop bridged by qasync.run().
- One ``DaemonClient`` connection (auto-spawns the daemon if absent).
- One ``MixtapeWindow`` (main UI) and one ``MixtapeTrayIcon`` (system
  tray / menu bar). The tray is the always-visible anchor; the window
  shows on demand.
- Sync, library switching, cookie refresh: all REST calls.
- Live state (sync progress, plug events, etc.): WS event stream piped
  into Qt signals so widgets can react on the UI thread.

Why this is a single process
----------------------------
The whole point of moving to PySide6 was to retire the dual-process
``pystray`` workaround. ``QSystemTrayIcon`` lives in the same Qt event
loop as the window, so there is no IPC, no PID file dance, no
``DETACHED_PROCESS``. Closing the window calls ``window.hide()``;
re-opening from the tray calls ``window.show()``."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import qasync
from PySide6 import QtCore, QtGui, QtWidgets

from ..client import DaemonClient, DaemonError, DaemonNotRunning


log = logging.getLogger("mixtape.desktop")


ICON_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "mixtape.png",
    Path(__file__).resolve().parents[3] / "mixtape.png",
]


def _icon() -> QtGui.QIcon:
    for p in ICON_CANDIDATES:
        if p.is_file():
            return QtGui.QIcon(str(p))
    # Fallback — system style icon so the tray isn't blank on missing asset.
    return QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.StandardPixmap.SP_MediaPlay
    )


# ── Window ──────────────────────────────────────────────────────────────


class MixtapeWindow(QtWidgets.QMainWindow):
    """Main window. Holds a playlist table, a status bar, a log pane."""

    sync_one_requested = QtCore.Signal()
    sync_all_requested = QtCore.Signal()
    refresh_cookies_requested = QtCore.Signal()
    refresh_update_requested = QtCore.Signal()
    apply_update_requested = QtCore.Signal()
    quit_requested = QtCore.Signal()
    set_active_library_requested = QtCore.Signal(str)
    set_close_to_tray_requested = QtCore.Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("mixtape")
        self.setWindowIcon(_icon())
        self.resize(960, 640)

        # Top status strip — bgutil / cookies / library / update.
        self._status_label = QtWidgets.QLabel("connecting…")
        self._status_label.setStyleSheet("padding: 6px 10px; color: #aaa;")
        self._status_label.setTextFormat(QtCore.Qt.TextFormat.RichText)

        # Library selector.
        self._lib_combo = QtWidgets.QComboBox()
        self._lib_combo.setMinimumWidth(180)
        self._lib_combo.currentTextChanged.connect(self._on_lib_combo_changed)

        # Close-to-tray checkbox.
        self._close_to_tray_cb = QtWidgets.QCheckBox("Close window to tray")
        self._close_to_tray_cb.toggled.connect(self.set_close_to_tray_requested.emit)

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setContentsMargins(8, 4, 8, 4)
        top_bar.addWidget(QtWidgets.QLabel("Library:"))
        top_bar.addWidget(self._lib_combo)
        top_bar.addStretch(1)
        top_bar.addWidget(self._close_to_tray_cb)

        # Playlist table.
        self._table = QtWidgets.QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["#", "Name", "Format", "Last sync", "Tracks", "Folder"])
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)

        # Action buttons.
        self._sync_one_btn = QtWidgets.QPushButton("Sync selected")
        self._sync_all_btn = QtWidgets.QPushButton("Sync all")
        self._refresh_cookies_btn = QtWidgets.QPushButton("Refresh cookies")
        self._update_btn = QtWidgets.QPushButton("Check update")
        self._sync_one_btn.clicked.connect(self.sync_one_requested.emit)
        self._sync_all_btn.clicked.connect(self.sync_all_requested.emit)
        self._refresh_cookies_btn.clicked.connect(self.refresh_cookies_requested.emit)
        self._update_btn.clicked.connect(self.refresh_update_requested.emit)

        action_bar = QtWidgets.QHBoxLayout()
        action_bar.addWidget(self._sync_one_btn)
        action_bar.addWidget(self._sync_all_btn)
        action_bar.addStretch(1)
        action_bar.addWidget(self._refresh_cookies_btn)
        action_bar.addWidget(self._update_btn)

        # Log pane.
        self._log = QtWidgets.QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setStyleSheet("font-family: ui-monospace, Menlo, Consolas, monospace;")

        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._status_label)
        v.addLayout(top_bar)
        v.addWidget(self._table, stretch=3)
        v.addLayout(action_bar)
        v.addWidget(self._log, stretch=1)
        self.setCentralWidget(central)

        # Sync progress — shown via status bar.
        self._sync_progress = QtWidgets.QProgressBar()
        self._sync_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._sync_progress)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self._close_to_tray_cb.isChecked():
            self.hide()
            event.ignore()
        else:
            event.accept()
            self.quit_requested.emit()

    # ── state pushes from the controller ────────────────────────────

    def set_status(self, html: str) -> None:
        self._status_label.setText(html)

    def set_libraries(self, names: list[str], active: str, close_to_tray: bool) -> None:
        # Block signals so updates don't fire requests.
        self._lib_combo.blockSignals(True)
        self._lib_combo.clear()
        self._lib_combo.addItems(names)
        if active in names:
            self._lib_combo.setCurrentText(active)
        self._lib_combo.blockSignals(False)

        self._close_to_tray_cb.blockSignals(True)
        self._close_to_tray_cb.setChecked(close_to_tray)
        self._close_to_tray_cb.blockSignals(False)

    def set_playlists(self, playlists: list[dict[str, Any]]) -> None:
        self._table.setRowCount(len(playlists))
        for i, p in enumerate(playlists):
            self._set_cell(i, 0, str(i + 1))
            self._set_cell(i, 1, p.get("name", "?"))
            self._set_cell(i, 2, p.get("format", "?"))
            self._set_cell(i, 3, p.get("last_sync") or "—")
            tc = p.get("track_count")
            self._set_cell(i, 4, str(tc) if tc else "—")
            self._set_cell(i, 5, p.get("relative_path") or "")
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QtWidgets.QTableWidgetItem(text)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, col, item)

    def selected_index(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return rows[0].row()

    def show_sync_progress(self, current: int, total: int) -> None:
        self._sync_progress.setRange(0, max(total, 1))
        self._sync_progress.setValue(current)
        self._sync_progress.setVisible(True)

    def hide_sync_progress(self) -> None:
        self._sync_progress.setVisible(False)

    def append_log(self, msg: str) -> None:
        self._log.appendHtml(msg)

    def _on_lib_combo_changed(self, text: str) -> None:
        if text:
            self.set_active_library_requested.emit(text)


# ── Tray icon ───────────────────────────────────────────────────────────


class MixtapeTrayIcon(QtWidgets.QSystemTrayIcon):
    open_requested = QtCore.Signal()
    sync_all_requested = QtCore.Signal()
    quit_requested = QtCore.Signal()

    def __init__(self, app: QtWidgets.QApplication) -> None:
        super().__init__(_icon())
        self.setToolTip("mixtape")

        menu = QtWidgets.QMenu()
        a_open = menu.addAction("Open mixtape")
        a_sync = menu.addAction("Sync all now")
        menu.addSeparator()
        a_quit = menu.addAction("Quit")
        a_open.triggered.connect(self.open_requested.emit)
        a_sync.triggered.connect(self.sync_all_requested.emit)
        a_quit.triggered.connect(self.quit_requested.emit)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()


# ── Controller ──────────────────────────────────────────────────────────


class DesktopController(QtCore.QObject):
    """Glue: routes Qt signals → DaemonClient REST calls, and routes
    daemon events → Qt slot calls on the UI thread."""

    def __init__(self, app: QtWidgets.QApplication, client: DaemonClient,
                 window: MixtapeWindow, tray: MixtapeTrayIcon) -> None:
        super().__init__()
        self._app = app
        self._client = client
        self._win = window
        self._tray = tray

        # Window → controller wiring.
        window.sync_one_requested.connect(lambda: self._launch(self._sync_one()))
        window.sync_all_requested.connect(lambda: self._launch(self._sync_all()))
        window.refresh_cookies_requested.connect(lambda: self._launch(self._refresh_cookies()))
        window.refresh_update_requested.connect(lambda: self._launch(self._refresh_update()))
        window.apply_update_requested.connect(lambda: self._launch(self._apply_update()))
        window.set_active_library_requested.connect(lambda n: self._launch(self._set_active(n)))
        window.set_close_to_tray_requested.connect(lambda v: self._launch(self._set_close_to_tray(v)))
        window.quit_requested.connect(self.quit)

        # Tray → controller wiring.
        tray.open_requested.connect(self.show_window)
        tray.sync_all_requested.connect(lambda: self._launch(self._sync_all()))
        tray.quit_requested.connect(self.quit)

        self._state: dict[str, Any] = {}
        self._libs: dict[str, Any] = {}
        self._playlists: list[dict[str, Any]] = []

    # ── public ───────────────────────────────────────────────────────

    def show_window(self) -> None:
        self._win.show()
        self._win.raise_()
        self._win.activateWindow()

    def quit(self) -> None:
        self._launch(self._shutdown_and_quit())

    # ── async helpers ────────────────────────────────────────────────

    @staticmethod
    def _launch(coro: Any) -> None:
        asyncio.ensure_future(coro)

    async def start(self) -> None:
        await self._refresh_state()
        asyncio.ensure_future(self._stream_events())

    async def _refresh_state(self) -> None:
        try:
            self._state = await self._client.status()
            self._libs = await self._client.libraries()
            self._playlists = await self._client.playlists()
        except DaemonError as e:
            self._win.append_log(f'<span style="color:#e55">daemon error: {e}</span>')
            return
        self._render_state()

    def _render_state(self) -> None:
        bgutil = self._state.get("bgutil", {}) or {}
        cookies = self._state.get("cookies", {}) or {}
        update = self._state.get("update")

        cookie_html = (
            '<span style="color:#7c7">✓ cookies valid</span>'
            if cookies.get("state") == "valid"
            else f'<span style="color:#e77">✗ cookies {cookies.get("state","?")}: {cookies.get("message","")}</span>'
        )
        bgutil_html = (
            '<span style="color:#7c7">✓ bgutil</span>'
            if bgutil.get("state") == "ok"
            else f'<span style="color:#e77">✗ bgutil: {bgutil.get("message","?")}</span>'
        )
        active = self._libs.get("active", "?")
        update_html = ""
        if update and update.get("behind"):
            update_html = f' &nbsp;—&nbsp; <span style="color:#fc7"><b>↑ {update.get("message","update")}</b></span>'

        n = len(self._playlists)
        self._win.set_status(
            f"<b>{n}</b> playlist(s) &nbsp; • &nbsp; {cookie_html} &nbsp; • &nbsp; "
            f"{bgutil_html} &nbsp; • &nbsp; library: <b>{active}</b>{update_html}"
        )

        names = [str(lib.get("name")) for lib in self._libs.get("libraries", [])]
        self._win.set_libraries(names, active, bool(self._libs.get("close_to_tray")))
        self._win.set_playlists(self._playlists)

    async def _stream_events(self) -> None:
        try:
            async for ev in self._client.stream_events_forever():
                self._handle_event(ev)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            log.exception("event stream errored")

    def _handle_event(self, ev: dict[str, Any]) -> None:
        name = ev.get("name", "")
        data = ev.get("data", {})
        if name == "sync.started":
            n = len(data.get("playlists", []))
            self._win.append_log(f'<span style="color:#7cf">▶</span> sync started — {n} playlist(s)')
            self._win.show_sync_progress(0, max(n, 1))
            self._tray.showMessage("mixtape", "Sync started", _icon())
        elif name == "sync.playlist_done":
            self._win.append_log(
                f'<span style="color:#7c7">✔</span> {data.get("name")} ({data.get("count")} tracks)'
            )
        elif name == "sync.error":
            self._win.append_log(f'<span style="color:#e55">✗ {data.get("message","?")}</span>')
        elif name == "sync.finished":
            self._win.hide_sync_progress()
            tag = "done" if data.get("ok") else "cancelled"
            self._win.append_log(f"<b>sync {tag}</b>")
            self._tray.showMessage("mixtape", f"Sync {tag}", _icon())
            self._launch(self._refresh_state())
        elif name == "library.changed":
            self._launch(self._refresh_state())
        elif name in ("cookies.status", "bgutil.status", "update.status"):
            # Status text update — re-fetch /status next render cycle.
            self._launch(self._refresh_state())
        elif name == "volume.added":
            label = data.get("label") or data.get("identifier")
            self._tray.showMessage("mixtape", f"Volume plugged: {label}", _icon())
        elif name == "volume.removed":
            self._tray.showMessage("mixtape", f"Volume unplugged: {data.get('identifier')}", _icon())
        elif name == "daemon.shutdown":
            self._win.append_log("<b>daemon shut down</b>")

    # ── REST-call coroutines (Qt signal targets) ─────────────────────

    async def _sync_one(self) -> None:
        idx = self._win.selected_index()
        if idx is None:
            self._win.append_log("<i>nothing selected</i>")
            return
        try:
            await self._client.sync(playlists=[idx])
        except DaemonError as e:
            self._win.append_log(f'<span style="color:#e55">sync failed: {e}</span>')

    async def _sync_all(self) -> None:
        try:
            await self._client.sync()
        except DaemonError as e:
            self._win.append_log(f'<span style="color:#e55">sync failed: {e}</span>')

    async def _refresh_cookies(self) -> None:
        await self._client.refresh_cookies()

    async def _refresh_update(self) -> None:
        await self._client.refresh_update()

    async def _apply_update(self) -> None:
        try:
            res = await self._client.apply_update()
        except DaemonError as e:
            self._win.append_log(f'<span style="color:#e55">update failed: {e}</span>')
            return
        self._win.append_log(f'<b>update apply:</b> {res}')

    async def _set_active(self, name: str) -> None:
        try:
            await self._client.set_active_library(name)
        except DaemonError as e:
            self._win.append_log(f'<span style="color:#e55">{e}</span>')

    async def _set_close_to_tray(self, enabled: bool) -> None:
        try:
            await self._client.set_close_to_tray(enabled)
        except DaemonError as e:
            self._win.append_log(f'<span style="color:#e55">{e}</span>')

    async def _shutdown_and_quit(self) -> None:
        # Don't shut the daemon down on every quit — only when the user
        # explicitly chooses Quit. The tray's Quit menu item is the
        # only path that calls this.
        try:
            # Future hook: ask daemon to shut down too if a setting says so.
            # For now, the daemon is independent and survives the UI.
            pass
        finally:
            self._app.quit()


# ── Entry point ─────────────────────────────────────────────────────────


def run_desktop() -> int:
    """Synchronous entry point wired into ``mixtape --desktop`` and
    used by default on Windows / macOS by app.main."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    assert isinstance(app, QtWidgets.QApplication)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(_icon())

    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        QtWidgets.QMessageBox.critical(
            None, "mixtape",
            "No system tray available on this desktop. Falling back to TUI.",
        )
        from ..tui import run_tui
        return run_tui()

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    async def boot() -> int:
        try:
            client = await DaemonClient.connect()
        except DaemonNotRunning as e:
            QtWidgets.QMessageBox.critical(
                None, "mixtape",
                f"Could not start the mixtape daemon: {e}",
            )
            return 2

        window = MixtapeWindow()
        tray = MixtapeTrayIcon(app)
        controller = DesktopController(app, client, window, tray)
        tray.show()
        # If close_to_tray was set, start hidden; else show the window.
        snap = await client.libraries()
        if snap.get("close_to_tray"):
            window.hide()
        else:
            window.show()
        await controller.start()
        return 0

    with loop:
        rc = loop.run_until_complete(boot())
        if rc != 0:
            return rc
        loop.run_forever()
    return 0
