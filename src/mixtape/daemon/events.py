"""WebSocket /events route — fans every bus event out to every
connected client with one queue per client.

Auth: we accept the bearer token in the ``Authorization`` header for
clients that can set it (most do over Sec-WebSocket-Protocol or
custom headers), AND as a ``?token=…`` query string fallback for
browser clients that can't set headers on the WS handshake. Both
paths go through the same compare_digest check.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from ..services import Application
from .auth import TOKEN


log = logging.getLogger("mixtape.daemon.events")


def make_events_router(app: Application) -> APIRouter:
    r = APIRouter()

    @r.websocket("/events")
    async def events_ws(ws: WebSocket) -> None:
        if not _authorized(ws):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        log.info("ws client connected (peer=%s)", ws.client)
        try:
            async with app.bus.subscribe() as q:
                while True:
                    ev = await q.get()
                    if ws.client_state != WebSocketState.CONNECTED:
                        return
                    try:
                        await ws.send_text(json.dumps(ev.to_wire(), default=str))
                    except (RuntimeError, WebSocketDisconnect):
                        return
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("ws stream errored")

    return r


def _authorized(ws: WebSocket) -> bool:
    auth = ws.headers.get("authorization") or ws.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        if TOKEN.matches(auth[len("bearer "):].strip()):
            return True
    qtok = ws.query_params.get("token")
    if qtok and TOKEN.matches(qtok):
        return True
    return False
