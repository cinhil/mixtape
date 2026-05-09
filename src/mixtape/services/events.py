"""Async pub/sub bus + event vocabulary used by every service.

Design notes
------------
- One bus per Application. Services publish; clients subscribe via
  ``bus.stream()`` (an async iterator) and unsubscribe by exiting the
  ``async with`` block.
- Events are plain dicts so the daemon can JSON-serialise them straight
  to the WebSocket without an extra serialisation pass. A typed dataclass
  carries the wire shape for callers that prefer type-checking.
- The bus never blocks publishers: each subscriber has its own queue;
  if a subscriber falls behind, its queue grows. We don't bound the
  queue (single-user, single-machine — bounding here causes lost
  events and weirder bugs than memory pressure ever will).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Literal


log = logging.getLogger("mixtape.bus")


EventName = Literal[
    # Sync lifecycle
    "sync.started",      # data: {library, playlists: [{idx, name, format}]}
    "sync.progress",     # data: {playlist_idx, track_idx, track_total, percent, track_title, source}
    "sync.track_done",   # data: {playlist_idx, track_idx, track_total, track_title, source}
    "sync.playlist_done",# data: {playlist_idx, name, count}
    "sync.log",          # data: {playlist_idx, message}
    "sync.error",        # data: {playlist_idx, message}
    "sync.finished",     # data: {ok, cancelled, library_name}
    # USB / volumes
    "volume.added",      # data: {identifier, label, mount_path, fs_type}
    "volume.removed",    # data: {identifier}
    "library.activated", # data: {library_name, path}
    "library.changed",   # data: (full library list snapshot)
    # Cookies / bgutil / updates
    "cookies.status",    # data: {state, message}
    "bgutil.status",     # data: {state, message}
    "update.status",     # data: {channel, current, latest, behind, message}
    # Daemon lifecycle
    "daemon.ready",      # data: {pid, started_at}
    "daemon.shutdown",   # data: {reason}
]


@dataclass
class Event:
    name: EventName
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._closed = False

    def publish(self, name: EventName, **data: Any) -> None:
        if self._closed:
            return
        ev = Event(name=name, data=data)
        for q in list(self._subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                # Won't happen — queues are unbounded — but defensive.
                log.warning("bus subscriber queue full, dropping event %s", name)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.append(q)
        try:
            yield q
        finally:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    async def stream(self) -> AsyncIterator[Event]:
        async with self.subscribe() as q:
            while True:
                ev = await q.get()
                yield ev

    def close(self) -> None:
        self._closed = True
        self._subscribers.clear()
