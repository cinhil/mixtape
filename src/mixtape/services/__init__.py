"""Mixtape's service layer — UI-agnostic orchestration of sync, watcher,
bgutil, cookies, libraries, updates.

The daemon owns one instance of each service; clients (TUI, desktop UI)
talk to the daemon over HTTP/WebSocket and never import these modules
directly. They're also re-usable by an in-process embedding (e.g. a
Qt application with the daemon embedded), but the daemon-and-clients
split is the supported deployment.
"""
from __future__ import annotations

from .events import Event, EventBus, EventName
from .application import Application

__all__ = ["Application", "Event", "EventBus", "EventName"]
