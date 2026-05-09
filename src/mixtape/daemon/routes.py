"""REST endpoints for the daemon. All routes require a bearer token."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from ..services import Application
from ..services.sync_service import SyncRunInProgress
from .auth import require_bearer
from .schema import (
    DaemonStatus,
    LibrarySnapshot,
    PlaylistOut,
    SetActiveRequest,
    SetCloseToTrayRequest,
    SimpleOk,
    SyncRequest,
    SyncResponse,
    UpdateApplyResult,
)


log = logging.getLogger("mixtape.daemon.routes")


def make_router(app: Application) -> APIRouter:
    """Bind a fresh Application instance to a router. The daemon's
    main module owns the Application — we just borrow it here."""
    r = APIRouter(dependencies=[Depends(require_bearer)])

    @r.get("/status", response_model=DaemonStatus)
    async def status() -> DaemonStatus:
        cookies = app.cookies.status
        upd = app.updates.status
        return DaemonStatus(
            pid=__import__("os").getpid(),
            started_at=app.started_at or 0.0,
            bgutil={"state": app.bgutil.state, "message": app.bgutil.message},
            cookies={"state": cookies.state, "message": cookies.message},
            update=(
                {
                    "channel": upd.channel,
                    "current": upd.current,
                    "latest": upd.latest,
                    "behind": upd.behind,
                    "message": upd.message,
                }
                if upd is not None else None
            ),
            sync_in_progress=app.sync.is_running,
        )

    @r.get("/libraries", response_model=LibrarySnapshot)
    async def list_libraries() -> LibrarySnapshot:
        return LibrarySnapshot(**(await app.library.snapshot()))

    @r.post("/libraries/active", response_model=SimpleOk)
    async def set_active(req: SetActiveRequest) -> SimpleOk:
        ok = await app.library.set_active_library(req.library)
        if not ok:
            raise HTTPException(404, f"unknown library: {req.library}")
        return SimpleOk()

    @r.post("/libraries/close-to-tray", response_model=SimpleOk)
    async def set_close_to_tray(req: SetCloseToTrayRequest) -> SimpleOk:
        await app.library.set_close_to_tray(req.enabled)
        return SimpleOk()

    @r.get("/libraries/{name}/playlists", response_model=list[PlaylistOut])
    async def list_playlists(name: str) -> list[PlaylistOut]:
        try:
            data = await app.library.list_playlists(name)
        except KeyError:
            raise HTTPException(404, f"unknown library: {name}")
        return [PlaylistOut(**d) for d in data]

    @r.get("/playlists", response_model=list[PlaylistOut])
    async def list_active_playlists() -> list[PlaylistOut]:
        data = await app.library.list_playlists(None)
        return [PlaylistOut(**d) for d in data]

    @r.post("/sync", response_model=SyncResponse)
    async def trigger_sync(req: SyncRequest) -> SyncResponse:
        try:
            res = await app.sync.sync(req.library, req.playlists)
        except SyncRunInProgress:
            raise HTTPException(409, "a sync is already running")
        except KeyError as e:
            raise HTTPException(404, str(e))
        return SyncResponse(**res)

    @r.post("/sync/cancel", response_model=SimpleOk)
    async def cancel_sync() -> SimpleOk:
        await app.sync.cancel()
        return SimpleOk()

    @r.post("/cookies/refresh", response_model=SimpleOk)
    async def refresh_cookies() -> SimpleOk:
        await app.cookies.refresh(force=True)
        return SimpleOk()

    @r.post("/update/refresh", response_model=SimpleOk)
    async def refresh_update() -> SimpleOk:
        await app.updates.refresh(force=True)
        return SimpleOk()

    @r.post("/update/apply", response_model=UpdateApplyResult)
    async def apply_update() -> UpdateApplyResult:
        ok, msg = await app.updates.apply_dev()
        return UpdateApplyResult(ok=ok, message=msg)

    @r.post("/shutdown", response_model=SimpleOk)
    async def shutdown() -> SimpleOk:
        # Schedule shutdown so we can return the response first.
        loop = asyncio.get_running_loop()
        loop.call_later(0.05, lambda: asyncio.create_task(_request_shutdown(app)))
        return SimpleOk()

    return r


async def _request_shutdown(app: Application) -> None:
    # Trigger uvicorn's lifespan shutdown by setting the global signal
    # the daemon's main installs. We just close the bus and stop
    # services here; the main task picks up the signal and exits.
    log.info("shutdown requested via REST")
    from .lifespan import request_shutdown
    request_shutdown()
