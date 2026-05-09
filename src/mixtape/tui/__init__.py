"""Thin Textual TUI — talks to the daemon over HTTP/WS, holds zero
domain state of its own.

Entry point: ``mixtape``. The application's __main__ dispatches to
``run_tui`` after ensuring the daemon is reachable.
"""
from __future__ import annotations

from .main import run_tui

__all__ = ["run_tui"]
