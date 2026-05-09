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
        # identifier → marker UUID (or "" for "no marker"). Lets us
        # skip the per-volume marker probe on duplicate change events
        # — find_marker_on_volume reads from disk + parses YAML.
        self._marker_cache: dict[str, str] = {}

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
            if vol.identifier not in self._marker_cache:
                await self._maybe_match_library(vol.identifier, str(vol.mount_path))
        for ident in change.removed:
            self._marker_cache.pop(ident, None)
            self._bus.publish("volume.removed", identifier=ident)
            await self._maybe_active_went_offline()

    async def _maybe_match_library(self, identifier: str, mount_path: str) -> None:
        marker_hit = await asyncio.to_thread(find_marker_on_volume, Path(mount_path))
        if not marker_hit:
            self._marker_cache[identifier] = ""
            return
        marker, marker_root = marker_hit
        self._marker_cache[identifier] = marker.uuid
        lib = self._library.config.get_library_by_uuid(marker.uuid)
        if not lib:
            return
        # Goes through the library service so the lock + library.changed
        # event are honoured (avoids racing other writers).
        await self._library.update_library_path(marker.uuid, str(marker_root))
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
