"""Sync orchestration — the only place that knows how to run a sync.

Used by the daemon (via REST `/sync` endpoints), embedded in the same
process as a Qt or TUI client when desired. Bridges the existing
synchronous ``sync_playlist`` (yt-dlp blocking call with a callback)
into the async event bus.

Concurrency model
-----------------
Only one sync run can be in flight at a time per process — we hold
``self._lock`` for the duration. Cancel via ``cancel()`` which sets a
``threading.Event`` the worker checks between tracks.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from ..beep import beep
from ..config import Library, Playlist
from ..downloader import ProgressEvent, sync_playlist
from ..platform_io import flush_filesystem
from .events import EventBus
from .library_service import LibraryService


log = logging.getLogger("mixtape.sync")


class SyncRunInProgress(RuntimeError):
    pass


class SyncService:
    def __init__(self, bus: EventBus, library: LibraryService) -> None:
        self._bus = bus
        self._library = library
        self._lock = asyncio.Lock()
        self._cancel_evt: threading.Event | None = None
        self._current: dict[str, Any] | None = None

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    @property
    def current(self) -> dict[str, Any] | None:
        return self._current

    async def cancel(self) -> bool:
        if self._cancel_evt is not None:
            self._cancel_evt.set()
            return True
        return False

    async def sync(self, library_name: str | None = None,
                   playlist_idxs: list[int] | None = None) -> dict[str, Any]:
        """Run a sync. ``library_name`` defaults to the active library.
        ``playlist_idxs`` defaults to all playlists in that library.
        Raises SyncRunInProgress if another sync is already running."""
        if self._lock.locked():
            raise SyncRunInProgress("a sync is already running")
        async with self._lock:
            return await self._run(library_name, playlist_idxs)

    async def _run(self, library_name: str | None, playlist_idxs: list[int] | None) -> dict[str, Any]:
        cfg = self._library.config
        if library_name is None:
            lib = cfg.active_library_obj()
        else:
            got = cfg.get_library(library_name)
            if got is None:
                raise KeyError(f"unknown library: {library_name}")
            lib = got
        all_playlists = await asyncio.to_thread(cfg.playlists_for, lib)
        if playlist_idxs is None:
            targets = list(enumerate(all_playlists))
        else:
            targets = [(i, all_playlists[i]) for i in playlist_idxs if 0 <= i < len(all_playlists)]
        if not targets:
            return {"ok": True, "cancelled": False, "library": lib.name, "synced": 0, "reason": "nothing to sync"}

        self._cancel_evt = threading.Event()
        self._current = {
            "library": lib.name,
            "playlists": [{"idx": i, "name": p.name, "format": p.format} for i, p in targets],
        }
        self._bus.publish("sync.started", **self._current)
        beep(1)

        loop = asyncio.get_running_loop()
        synced = 0
        try:
            for ui_idx, (cfg_idx, pl) in enumerate(targets):
                if self._cancel_evt.is_set():
                    self._bus.publish(
                        "sync.log",
                        playlist_idx=cfg_idx,
                        message=f"Skipped {pl.name} (cancelled)",
                    )
                    continue
                try:
                    count = await self._sync_one(loop, pl, lib, ui_idx)
                    await self._library.mark_synced(pl, count)
                    synced += 1
                    self._bus.publish(
                        "sync.playlist_done",
                        playlist_idx=cfg_idx, name=pl.name, count=count,
                    )
                except Exception as e:  # noqa: BLE001
                    log.exception("playlist %r failed", pl.name)
                    self._bus.publish(
                        "sync.error", playlist_idx=cfg_idx, message=str(e),
                    )
            try:
                await asyncio.to_thread(flush_filesystem)
            except Exception:
                log.warning("filesystem flush failed", exc_info=True)
            cancelled = self._cancel_evt.is_set()
            if not cancelled:
                beep(2)
            self._bus.publish(
                "sync.finished",
                ok=not cancelled, cancelled=cancelled, library_name=lib.name,
                synced=synced,
            )
            return {"ok": not cancelled, "cancelled": cancelled, "library": lib.name, "synced": synced}
        finally:
            self._cancel_evt = None
            self._current = None

    async def _sync_one(self, loop: asyncio.AbstractEventLoop,
                        playlist: Playlist, library: Library,
                        ui_idx: int) -> int:
        cancel = self._cancel_evt
        bus = self._bus

        def post(ev: ProgressEvent) -> None:
            # Translate downloader progress events into bus events,
            # publishing on the loop thread to keep ordering deterministic.
            # call_soon_threadsafe only accepts positional args, so we
            # build a no-arg lambda that captures the kwargs.
            def _emit_progress(p=dict(
                playlist_idx=ev.playlist_idx, track_idx=ev.track_idx,
                track_total=ev.track_total, track_title=ev.track_title,
                source=ev.source, percent=ev.percent, message=ev.message,
            )):
                bus.publish("sync.progress", **p)

            def _emit_done(p=dict(
                playlist_idx=ev.playlist_idx, track_idx=ev.track_idx,
                track_total=ev.track_total, track_title=ev.track_title,
                source=ev.source,
            )):
                bus.publish("sync.track_done", **p)

            def _log(msg: str = ev.message, idx: int = ev.playlist_idx):
                bus.publish("sync.log", playlist_idx=idx, message=msg)

            def _err(msg: str = ev.message, idx: int = ev.playlist_idx):
                bus.publish("sync.error", playlist_idx=idx, message=msg)

            kind = ev.kind
            if kind == "start" or kind == "log" or kind == "done":
                loop.call_soon_threadsafe(_log)
            elif kind == "progress":
                loop.call_soon_threadsafe(_emit_progress)
            elif kind == "finished":
                loop.call_soon_threadsafe(_emit_done)
            elif kind == "cancelled":
                loop.call_soon_threadsafe(_log, f"⏹ {ev.message}")
            elif kind == "error":
                loop.call_soon_threadsafe(_err)

        # sync_playlist is blocking — run in a worker thread.
        return await asyncio.to_thread(
            sync_playlist, playlist, library, ui_idx, post, cancel,
        )
