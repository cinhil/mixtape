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

    async def create_playlist_from_url(self, url: str, *,
                                        name: str | None = None,
                                        fmt: str | None = None,
                                        quality: str | None = None,
                                        requires_cookies: bool = True,
                                        ) -> Playlist:
        """Resolve a YouTube playlist URL into a Playlist + write it to
        the active library. Fetches metadata if ``name`` is unset."""
        from ..downloader import fetch_playlist_meta
        async with self._lock:
            resolved_name = name or ""
            if not resolved_name:
                meta = await asyncio.to_thread(fetch_playlist_meta, url)
                resolved_name = meta.title or "Playlist"
            playlist = Playlist(
                name=resolved_name,
                url=url,
                format=fmt or self._cfg.defaults.format,
                quality=quality or self._cfg.defaults.quality,
                requires_cookies=requires_cookies,
            )
            await asyncio.to_thread(self._cfg.add_playlist, playlist)
            self._bus.publish("library.changed", **self._snapshot())
            return playlist

    async def update_playlist(self, playlist: Playlist) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.update_playlist, playlist)
            self._bus.publish("library.changed", **self._snapshot())

    async def update_playlist_by_idx(self, idx: int, *,
                                      name: str | None = None,
                                      url: str | None = None,
                                      fmt: str | None = None,
                                      quality: str | None = None,
                                      requires_cookies: bool | None = None,
                                      ) -> Playlist | None:
        async with self._lock:
            lib = self._cfg.active_library_obj()
            playlists = await asyncio.to_thread(self._cfg.playlists_for, lib)
            if not (0 <= idx < len(playlists)):
                return None
            p = playlists[idx]
            if name is not None: p.name = name
            if url is not None: p.url = url
            if fmt is not None: p.format = fmt
            if quality is not None: p.quality = quality
            if requires_cookies is not None: p.requires_cookies = requires_cookies
            await asyncio.to_thread(self._cfg.update_playlist, p)
            self._bus.publish("library.changed", **self._snapshot())
            return p

    async def remove_playlist(self, playlist: Playlist, also_files: bool = False) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.remove_playlist, playlist, also_files=also_files)
            self._bus.publish("library.changed", **self._snapshot())

    async def remove_playlist_by_idx(self, idx: int, also_files: bool = False) -> Playlist | None:
        async with self._lock:
            lib = self._cfg.active_library_obj()
            playlists = await asyncio.to_thread(self._cfg.playlists_for, lib)
            if not (0 <= idx < len(playlists)):
                return None
            p = playlists[idx]
            await asyncio.to_thread(self._cfg.remove_playlist, p, also_files=also_files)
            self._bus.publish("library.changed", **self._snapshot())
            return p

    async def mark_synced(self, playlist: Playlist, track_count: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.mark_synced, playlist, track_count)

    async def add_library(self, name: str, path: str, *,
                          volume_name: str = "", auto_sync: bool = False,
                          uuid: str = "", marker_target_root: str | None = None) -> None:
        """Add a library entry. If ``marker_target_root`` is provided, write
        a ``.mixtape`` marker (UUID + name) into that root so the device
        becomes recognisable across machines."""
        from .. import config as _cfg_mod
        async with self._lock:
            existing = self._cfg.get_library(name)
            if existing is not None:
                raise ValueError(f"library {name!r} already exists")
            lib = Library(
                name=name, path=path,
                volume_name=volume_name, auto_sync=auto_sync, uuid=uuid,
            )
            if marker_target_root:
                lib.uuid = await asyncio.to_thread(
                    _cfg_mod._ensure_local_marker,
                    Path(marker_target_root).expanduser(),
                    name,
                )
            await asyncio.to_thread(self._cfg.add_library, lib)
            self._bus.publish("library.changed", **self._snapshot())

    async def remove_library(self, name: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cfg.remove_library, name)
            self._bus.publish("library.changed", **self._snapshot())

    async def register_volume(self, mount_path: str, fallback_name: str | None = None) -> dict[str, Any]:
        """Either link an existing library to a freshly-detected volume's
        marker UUID, or create a new library on that volume.

        Returns the resulting library snapshot (name, path, uuid)."""
        from ..library_marker import find_marker_on_volume
        from .. import config as _cfg_mod
        async with self._lock:
            mount = Path(mount_path).expanduser()
            if not mount.is_dir():
                raise FileNotFoundError(f"not a directory: {mount}")
            marker_hit = await asyncio.to_thread(find_marker_on_volume, mount)
            if marker_hit:
                marker, marker_root = marker_hit
                # If we already know this UUID, just refresh the path.
                lib = self._cfg.get_library_by_uuid(marker.uuid)
                if lib is not None:
                    lib.path = str(marker_root)
                    await asyncio.to_thread(self._cfg.save)
                    self._bus.publish("library.changed", **self._snapshot())
                    return {"name": lib.name, "path": lib.path, "uuid": lib.uuid, "created": False}
                # Marker present but not registered → adopt with the marker name.
                lib = Library(
                    name=marker.name, path=str(marker_root), uuid=marker.uuid,
                )
                await asyncio.to_thread(self._cfg.add_library, lib)
                self._bus.publish("library.changed", **self._snapshot())
                return {"name": lib.name, "path": lib.path, "uuid": lib.uuid, "created": True}
            # No marker → create one + register a fresh library.
            name = fallback_name or mount.name or "USB"
            uuid = await asyncio.to_thread(
                _cfg_mod._ensure_local_marker, mount, name,
            )
            lib = Library(name=name, path=str(mount), uuid=uuid)
            await asyncio.to_thread(self._cfg.add_library, lib)
            self._bus.publish("library.changed", **self._snapshot())
            return {"name": lib.name, "path": lib.path, "uuid": lib.uuid, "created": True}

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
