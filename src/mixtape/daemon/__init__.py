"""Mixtape daemon — long-running process that owns the services and
exposes them over local-loopback HTTP + WebSocket.

Entry point: ``mixtape --daemon``. Bootstrap writes
``state/api.json`` so clients can discover the port + bearer token.
"""
from __future__ import annotations

from .bootstrap import (
    API_FILE_NAME,
    DaemonInfo,
    read_daemon_info,
    write_daemon_info,
    clear_daemon_info,
)

__all__ = [
    "API_FILE_NAME",
    "DaemonInfo",
    "read_daemon_info",
    "write_daemon_info",
    "clear_daemon_info",
]
