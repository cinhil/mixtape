"""USB watcher — wraps platform_io.VolumeWatcher (which polls in a
worker thread) and translates plug events into bus messages.

Identity resolution (volume → library) lives here, not in the UI:
when a known device's marker UUID matches a registered library, we
update the library's path and switch active. Auto-sync is the
SyncService's job.
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
        # identifier → (marker UUID or None, last-seen mount_path).
        # The cache exists so duplicate plug events skip the disk-walk +
        # YAML parse in find_marker_on_volume; we still re-call
        # update_library_path when the mount changes (USB drive keeps
        # its identifier across a remount-with-different-letter).
        self._marker_cache: dict[str, tuple[str | None, str]] = {}

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._watcher = VolumeWatcher(self._on_change)
        await asyncio.to_thread(self._watcher.start)
        # VolumeWatcher seeds its `_known` set with whatever is mounted
        # *now*, so its first `VolumeChange` only fires on subsequent
        # plug events. That means a USB drive plugged in BEFORE the
        # daemon started is invisible to _maybe_match_library. Probe
        # the seed manually.
        try:
            initial = await asyncio.to_thread(self._watcher.backend.list_volumes)
        except Exception:  # noqa: BLE001
            initial = []
        for vol in initial:
            await self._maybe_match_library(vol.identifier, str(vol.mount_path))

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
            await self._maybe_match_library(vol.identifier, str(vol.mount_path))
        for ident in change.removed:
            self._marker_cache.pop(ident, None)
            self._bus.publish("volume.removed", identifier=ident)
            await self._maybe_active_went_offline()

    async def _maybe_match_library(self, identifier: str, mount_path: str) -> None:
        cached = self._marker_cache.get(identifier)
        if cached is None:
            marker_hit = await asyncio.to_thread(find_marker_on_volume, Path(mount_path))
            if not marker_hit:
                self._marker_cache[identifier] = (None, mount_path)
                return
            marker, marker_root = marker_hit
            self._marker_cache[identifier] = (marker.uuid, str(marker_root))
            await self._reconcile(marker.uuid, str(marker_root))
            return
        cached_uuid, cached_path = cached
        if cached_path == mount_path:
            return
        # Same identifier, different mount — skip the marker probe but
        # still reconcile the registered library's path.
        self._marker_cache[identifier] = (cached_uuid, mount_path)
        if cached_uuid is not None:
            await self._reconcile(cached_uuid, mount_path)

    async def _reconcile(self, uuid: str, mount_path: str) -> None:
        lib = await self._library.get_library_by_uuid(uuid)
        if lib is None:
            return
        # update_library_path is locked + emits library.changed itself.
        await self._library.update_library_path(uuid, mount_path)
        await self._library.set_active_library(lib.name)

    async def _maybe_active_went_offline(self) -> None:
        await self._library.ensure_active_online()
