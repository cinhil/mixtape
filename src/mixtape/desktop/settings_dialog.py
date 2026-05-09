"""Settings dialog for the desktop UI — autostart, close-to-tray, daemon."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .. import autostart


class SettingsDialog(QtWidgets.QDialog):
    close_to_tray_changed = QtCore.Signal(bool)
    shutdown_daemon_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget,
                 close_to_tray: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("mixtape settings")
        self.resize(540, 280)

        v = QtWidgets.QVBoxLayout(self)

        # Autostart group
        autostart_box = QtWidgets.QGroupBox("Autostart at login")
        ag = QtWidgets.QFormLayout(autostart_box)
        self._autostart_cb = QtWidgets.QCheckBox("Start the mixtape daemon at login")
        self._autostart_cb.setEnabled(autostart.is_supported())
        if autostart.is_supported():
            self._autostart_cb.setChecked(autostart.is_enabled())
            self._autostart_cb.toggled.connect(self._on_autostart_toggled)
        ag.addRow(self._autostart_cb)
        ag.addRow(QtWidgets.QLabel(
            f"<small>Drops a launcher at <code>{_autostart_target_hint()}</code></small>"
        ))
        v.addWidget(autostart_box)

        # Window behaviour
        win_box = QtWidgets.QGroupBox("Window")
        wg = QtWidgets.QFormLayout(win_box)
        self._close_to_tray_cb = QtWidgets.QCheckBox("Close window to system tray (keep running)")
        self._close_to_tray_cb.setChecked(bool(close_to_tray))
        self._close_to_tray_cb.toggled.connect(self.close_to_tray_changed.emit)
        wg.addRow(self._close_to_tray_cb)
        v.addWidget(win_box)

        # Daemon
        daemon_box = QtWidgets.QGroupBox("Daemon")
        dg = QtWidgets.QFormLayout(daemon_box)
        shutdown_btn = QtWidgets.QPushButton("Shutdown daemon")
        shutdown_btn.clicked.connect(self.shutdown_daemon_requested.emit)
        dg.addRow(shutdown_btn)
        dg.addRow(QtWidgets.QLabel(
            "<small>The daemon is a separate process. Stopping it from "
            "here doesn't close this window.</small>"
        ))
        v.addWidget(daemon_box)

        v.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)

    def _on_autostart_toggled(self, value: bool) -> None:
        ok = autostart.enable() if value else autostart.disable()
        if not ok:
            self._autostart_cb.blockSignals(True)
            self._autostart_cb.setChecked(not value)
            self._autostart_cb.blockSignals(False)
            QtWidgets.QMessageBox.warning(
                self, "mixtape", "Could not change the autostart entry.",
            )


def _autostart_target_hint() -> str:
    import sys
    if sys.platform == "win32":
        return r"%APPDATA%\…\Startup\mixtape-daemon.lnk"
    if sys.platform == "darwin":
        return "~/Library/LaunchAgents/com.cinhil.mixtape.daemon.plist"
    return "~/.config/autostart/mixtape-daemon.desktop"
