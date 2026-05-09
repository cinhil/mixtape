"""Library + playlist + active-library management. Wraps Config /
manifest as the single writer of disk. Other services / clients ask
this one to mutate; never touch Config directly from a UI.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..config import Config, Library, Playlist
from .events import EventBus


log = logging.getLogger("mixtape.library")


class LibraryService:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = asyncio.Lock()
        self._cfg = Config.load()

    @property
    def config(self) -> Config:
        return self._cfg

    async def reload(self) -> Config:
        async with self._lock:
            self._cfg = await asyncio.to_thread(Config.load)
            self._bus.publish("library.changed", **self._snapshot())
            return self._cfg

    def _snapshot(self) -> dict[str, Any]:
        return {
            "active": self._cfg.active_library,
            "libraries": [asdict(lib) for lib in self._cfg.libraries],
            "close_to_tray": self._cfg.close_to_tray,
        }

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self._snapshot()

    async def active_library(self) -> Library:
        async with self._lock:
            return self._cfg.active_library_obj()

    async def list_playlists(self, library_name: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            if library_name is None:
                lib = self._cfg.active_library_obj()
            else:
                got = self._cfg.get_library(library_name)
                if got is None:
                    raise KeyError(library_name)
                lib = got
            playlists = await asyncio.to_thread(self._cfg.playlists_for, lib)
            return [self._playlist_dict(p) for p in playlists]

    @staticmethod
    def _playlist_dict(p: Playlist) -> dict[str, Any]:
        return {
            "name": p.name,
            "url": p.url,
            "format": p.format,
            "quality": p.quality,
            "relative_path": p.relative_path,
            "last_sync": p.last_sync,
            "track_count": p.track_count,
            "requires_cookies": p.requires_cookies,
        }

    async def set_active_library(self, name: str) -> bool:
        async with self._lock:
            if not self._cfg.get_library(name):
                return False
            self._cfg.set_active_library(name)
            await asyncio.to_thread(self._cfg.save)
            lib = self._cfg.active_library_obj()
            self._bus.publish("library.activated", library_name=lib.name, path=str(lib.path))
            self._bus.publish("library.changed", **self._snapshot())
            return True

    async def set_close_to_tray(self, enabled: bool) -> None:
        async with self._lock:
            self._cfg.close_to_tray = bool(enabled)
            await asyncio.to_thread(self._cfg.save)
            self._bus.publish("library.changed", **self._snapshot())

    async def add_playlist(self, playlist: Playlist) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.add_playlist, playlist)
            self._bus.publish("library.changed", **self._snapshot())

    async def update_playlist(self, playlist: Playlist) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.update_playlist, playlist)
            self._bus.publish("library.changed", **self._snapshot())

    async def remove_playlist(self, playlist: Playlist, also_files: bool = False) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.remove_playlist, playlist, also_files=also_files)
            self._bus.publish("library.changed", **self._snapshot())

    async def mark_synced(self, playlist: Playlist, track_count: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.mark_synced, playlist, track_count)

    async def get_playlist(self, library_name: str | None, idx: int) -> Playlist | None:
        async with self._lock:
            if library_name is None:
                lib = self._cfg.active_library_obj()
            else:
                got = self._cfg.get_library(library_name)
                if got is None:
                    return None
                lib = got
            playlists = await asyncio.to_thread(self._cfg.playlists_for, lib)
            if 0 <= idx < len(playlists):
                return playlists[idx]
            return None
