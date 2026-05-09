"""USB watcher — wraps platform_io.VolumeWatcher (which polls in a
worker thread) and translates plug events into bus messages.

Identity resolution (volume → library) lives here, not in the UI:
when a known device's marker UUID matches a registered library, we
emit ``library.activated`` with the new mount path and let the rest
of the stack react. Auto-sync is the SyncService's job.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..library_marker import find_marker_on_volume
from ..platform_io import VolumeChange, VolumeWatcher
from .events import EventBus
from .library_service import LibraryService


log = logging.getLogger("mixtape.watcher")


class WatcherService:
    def __init__(self, bus: EventBus, library: LibraryService) -> None:
        self._bus = bus
        self._library = library
        self._watcher: VolumeWatcher | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._watcher = VolumeWatcher(self._on_change)
        # VolumeWatcher.start() spawns its own thread — quick.
        await asyncio.to_thread(self._watcher.start)

    async def stop(self) -> None:
        if self._watcher:
            await asyncio.to_thread(self._watcher.stop)
            self._watcher = None

    # Called from VolumeWatcher's worker thread → re-enter the loop.
    def _on_change(self, change: VolumeChange) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(asyncio.create_task, self._handle_change(change))

    async def _handle_change(self, change: VolumeChange) -> None:
        for vol in change.added:
            self._bus.publish(
                "volume.added",
                identifier=vol.identifier,
                label=vol.label,
                mount_path=str(vol.mount_path),
                fs_type=vol.fs_type,
            )
            await self._maybe_match_library(str(vol.mount_path))
        for ident in change.removed:
            self._bus.publish("volume.removed", identifier=ident)
            await self._maybe_active_went_offline()

    async def _maybe_match_library(self, mount_path: str) -> None:
        cfg = self._library.config
        # Marker-based match — the canonical identity. The legacy
        # label-fallback path that used to live here is intentionally
        # omitted: marker UUIDs are written by mixtape on first
        # registration so any device created with this version (or any
        # older one that's been touched once) carries one.
        marker_hit = await asyncio.to_thread(find_marker_on_volume, Path(mount_path))
        if marker_hit:
            marker, marker_root = marker_hit
            lib = cfg.get_library_by_uuid(marker.uuid)
            if lib:
                new_path = str(marker_root)
                if lib.path != new_path:
                    lib.path = new_path
                    await asyncio.to_thread(cfg.save)
                await self._library.set_active_library(lib.name)

    async def _maybe_active_went_offline(self) -> None:
        active = (await self._library.active_library())
        path = Path(active.path).expanduser()
        if path.is_dir():
            return
        # Active library went offline — switch to first online fallback.
        cfg = self._library.config
        fallback = next(
            (lib for lib in cfg.libraries if lib.online and lib.name != active.name),
            None,
        )
        if fallback is None and cfg.libraries:
            fallback = cfg.libraries[0]
        if fallback and fallback.name != cfg.active_library:
            await self._library.set_active_library(fallback.name)
