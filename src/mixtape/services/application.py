"""Top-level wiring of all services into one Application.

A daemon process holds exactly one of these. A future single-process
shell (Qt with the daemon embedded) could too — same lifecycle.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from .bgutil_service import BgutilService
from .cookie_service import CookieService
from .events import EventBus
from .library_service import LibraryService
from .sync_service import SyncService
from .update_service import UpdateService
from .volume_service import VolumeService
from .watcher_service import WatcherService


log = logging.getLogger("mixtape.app")


class Application:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.library = LibraryService(self.bus)
        self.bgutil = BgutilService(self.bus)
        self.watcher = WatcherService(self.bus, self.library)
        self.cookies = CookieService(self.bus)
        self.updates = UpdateService(self.bus)
        self.sync = SyncService(self.bus, self.library)
        self.volumes = VolumeService()
        self._started_at: float | None = None

    async def start(self) -> None:
        log.info("application starting (pid %d)", os.getpid())
        # bgutil's deno spawn and the volume watcher's first poll both
        # take noticeable wall-clock time on a cold cache; run them
        # together so startup is dominated by whichever is slower.
        await asyncio.gather(self.bgutil.start(), self.watcher.start())
        # cookies + updates do network I/O; never block daemon ready on them.
        asyncio.create_task(self.cookies.start())
        asyncio.create_task(self.updates.start())
        self._started_at = time.time()
        self.bus.publish("daemon.ready", pid=os.getpid(), started_at=self._started_at)

    async def stop(self) -> None:
        log.info("application stopping")
        self.bus.publish("daemon.shutdown", reason="explicit-stop")
        # Cancel in reverse start order. Best-effort: never raise from stop.
        for fn in (self.updates.stop, self.cookies.stop, self.watcher.stop, self.bgutil.stop):
            try:
                await fn()
            except Exception:  # noqa: BLE001
                log.warning("error stopping service %s", fn, exc_info=True)
        self.bus.close()

    @property
    def started_at(self) -> float | None:
        return self._started_at
