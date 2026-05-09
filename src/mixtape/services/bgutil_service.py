"""Bgutil POT-server lifecycle — wraps the existing BgutilServer in
async-friendly form so the daemon can supervise it on its asyncio loop.

Most of the heavy lifting (deno discovery, port-bind, Windows V6ONLY
fallback) lives in mixtape.bgutil_server; this module is the
service-layer adapter that exposes start/stop and emits status events.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from ..bgutil_server import BgutilServer, is_server_running
from .events import EventBus


log = logging.getLogger("mixtape.bgutil")


BgutilState = Literal["pending", "ok", "fail", "stopped"]


class BgutilService:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._server = BgutilServer()
        self._state: BgutilState = "pending"
        self._message = ""
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BgutilState:
        return self._state

    @property
    def message(self) -> str:
        return self._message

    @property
    def url(self) -> str:
        return self._server.url

    async def start(self) -> tuple[bool, str]:
        async with self._lock:
            ok, msg = await asyncio.to_thread(self._server.start)
            self._state = "ok" if ok else "fail"
            self._message = msg
            self._bus.publish("bgutil.status", state=self._state, message=msg)
            return ok, msg

    async def stop(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._server.stop)
            self._state = "stopped"
            self._message = ""
            self._bus.publish("bgutil.status", state="stopped", message="")

    async def is_alive(self) -> bool:
        return await asyncio.to_thread(is_server_running)
