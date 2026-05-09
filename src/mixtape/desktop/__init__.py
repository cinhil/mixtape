"""PySide6 desktop UI — main window + native system-tray icon (or
macOS menu-bar item via Qt's QSystemTrayIcon → NSStatusItem mapping).

One process, one Qt event loop, asyncio bridged via qasync. The
window can hide to tray / menu bar; closing it doesn't quit the app
(unless the user picks Quit from the tray).

Requires the ``desktop`` extra:  uv sync --extra desktop
"""
from __future__ import annotations

from .main import run_desktop

__all__ = ["run_desktop"]
