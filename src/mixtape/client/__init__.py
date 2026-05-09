"""Async API client for the mixtape daemon. Used by the Textual TUI
client and the PySide6 desktop UI.

Typical usage
-------------
    async with DaemonClient.connect() as client:
        await client.refresh_cookies()
        async for ev in client.events():
            handle(ev)

``DaemonClient.connect`` reads ``STATE_DIR/api.json``; if it's missing
or stale it spawns the daemon (best-effort) and retries a few times.
"""
from __future__ import annotations

from .client import DaemonClient, DaemonNotRunning, DaemonError

__all__ = ["DaemonClient", "DaemonNotRunning", "DaemonError"]
