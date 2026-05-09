"""Daemon lifespan — process-wide shutdown signalling that's accessible
from REST handlers without a circular import dance."""
from __future__ import annotations

import asyncio


_shutdown_event: asyncio.Event | None = None


def install_shutdown_event(event: asyncio.Event) -> None:
    global _shutdown_event
    _shutdown_event = event


def request_shutdown() -> None:
    if _shutdown_event is not None:
        _shutdown_event.set()


def shutdown_event() -> asyncio.Event | None:
    return _shutdown_event
