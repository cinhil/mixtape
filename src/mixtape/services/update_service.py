"""Update-availability + apply service. Wraps update_check (which
already memoises behind get_update_status) and exposes apply hooks
the daemon's REST surface can call.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess

from ..update_check import (
    UpdateStatus,
    find_repo_dir,
    get_update_status,
    invalidate_cache,
)
from .events import EventBus


log = logging.getLogger("mixtape.update")


PERIODIC_INTERVAL_S = 60 * 60  # 1 hour


class UpdateService:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._status: UpdateStatus | None = None
        self._task: asyncio.Task | None = None

    @property
    def status(self) -> UpdateStatus | None:
        return self._status

    async def start(self) -> None:
        await self.refresh(force=False)
        self._task = asyncio.create_task(self._periodic())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def refresh(self, *, force: bool = False) -> UpdateStatus | None:
        if force:
            await asyncio.to_thread(invalidate_cache)
        status = await asyncio.to_thread(get_update_status, force)
        prev, self._status = self._status, status
        if status is not None and self._is_change(prev, status):
            self._bus.publish(
                "update.status",
                channel=status.channel,
                current=status.current,
                latest=status.latest,
                behind=status.behind,
                message=status.message,
            )
        return status

    @staticmethod
    def _is_change(prev: UpdateStatus | None, new: UpdateStatus) -> bool:
        if prev is None:
            return True
        return (prev.current, prev.latest, prev.behind, prev.message) != (
            new.current, new.latest, new.behind, new.message
        )

    async def apply_dev(self) -> tuple[bool, str]:
        repo = find_repo_dir()
        if not repo:
            return False, "no .git ancestor — can't pull"
        try:
            proc = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["git", "-C", str(repo), "pull", "--ff-only"],
                    capture_output=True, text=True, timeout=60,
                )
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            return False, str(e)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "git pull failed").strip()
        await self.refresh(force=True)  # also invalidates the cache
        return True, (proc.stdout or "updated").strip()

    async def _periodic(self) -> None:
        try:
            while True:
                await asyncio.sleep(PERIODIC_INTERVAL_S)
                await self.refresh(force=True)
        except asyncio.CancelledError:
            pass
