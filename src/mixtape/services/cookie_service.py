"""Cookie validity service — wraps the existing cookies_check logic in
the same async/event-bus shape as the others, with a periodic refresh
so the UI doesn't need to poll."""
from __future__ import annotations

import asyncio
import logging

from ..config import validate_cookies_text, write_cookies
from ..cookies_check import CookieStatus, get_cookie_status, invalidate_cache
from .events import EventBus


log = logging.getLogger("mixtape.cookies")


PERIODIC_INTERVAL_S = 60 * 60  # re-check every hour even if nothing happened


class CookieService:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._status: CookieStatus = CookieStatus(state="unknown", message="not yet checked")
        self._task: asyncio.Task | None = None

    @property
    def status(self) -> CookieStatus:
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

    async def write(self, content: str) -> CookieStatus:
        """Replace the cookies file with ``content`` (Netscape format) and
        re-validate immediately."""
        normalised = validate_cookies_text(content)
        await asyncio.to_thread(write_cookies, normalised)
        return await self.refresh(force=True)

    async def refresh(self, *, force: bool = False, announce: bool = True) -> CookieStatus:
        if force:
            await asyncio.to_thread(invalidate_cache)
        if announce:
            # Optimistic "checking…" so user-initiated refreshes show a
            # spinner. Skip from the periodic loop where it would just
            # flicker the UI for nobody.
            self._bus.publish("cookies.status", state="unknown", message="checking…")
        status = await asyncio.to_thread(get_cookie_status, force)
        prev, self._status = self._status, status
        if (prev.state, prev.message) != (status.state, status.message):
            self._bus.publish("cookies.status", state=status.state, message=status.message)
        return status

    async def _periodic(self) -> None:
        try:
            while True:
                await asyncio.sleep(PERIODIC_INTERVAL_S)
                # Quiet refresh — only emits if the status actually changed.
                await self.refresh(force=True, announce=False)
        except asyncio.CancelledError:
            pass
