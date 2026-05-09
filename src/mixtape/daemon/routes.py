"""REST endpoints for the daemon. All routes require a bearer token."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from ..services import Application
from ..services.sync_service import SyncRunInProgress
from .auth import require_bearer
from .schema import (
    AddLibraryRequest,
    AddPlaylistRequest,
    CookieStatusOut,
    DaemonStatus,
    LibrarySnapshot,
    PlaylistOut,
    RegisterVolumeRequest,
    RegisterVolumeResult,
    SetActiveRequest,
    SetCloseToTrayRequest,
    SetCookiesRequest,
    SimpleOk,
    SyncRequest,
    SyncResponse,
    UpdateApplyResult,
    UpdatePlaylistRequest,
    VolumeOut,
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

    @r.post("/cookies", response_model=CookieStatusOut)
    async def set_cookies(req: SetCookiesRequest) -> CookieStatusOut:
        try:
            status = await app.cookies.write(req.content)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return CookieStatusOut(state=status.state, message=status.message, ok=status.ok)

    @r.post("/libraries", response_model=SimpleOk, status_code=201)
    async def add_library(req: AddLibraryRequest) -> SimpleOk:
        try:
            await app.library.add_library(
                name=req.name, path=req.path,
                volume_name=req.volume_name, auto_sync=req.auto_sync,
                uuid=req.uuid, create_marker=req.create_marker,
            )
        except ValueError as e:
            raise HTTPException(409, str(e))
        return SimpleOk()

    @r.delete("/libraries/{name}", response_model=SimpleOk)
    async def remove_library(name: str) -> SimpleOk:
        await app.library.remove_library(name)
        return SimpleOk()

    @r.post("/libraries/register-volume", response_model=RegisterVolumeResult)
    async def register_volume(req: RegisterVolumeRequest) -> RegisterVolumeResult:
        try:
            res = await app.library.register_volume(req.mount_path, req.fallback_name)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))
        return RegisterVolumeResult(**res)

    @r.get("/volumes", response_model=list[VolumeOut])
    async def list_volumes() -> list[VolumeOut]:
        data = await app.volumes.list()
        return [VolumeOut(**v) for v in data]

    @r.post("/playlists", response_model=PlaylistOut, status_code=201)
    async def add_playlist(req: AddPlaylistRequest) -> PlaylistOut:
        try:
            p = await app.library.create_playlist_from_url(
                req.url, name=req.name, fmt=req.format, quality=req.quality,
                requires_cookies=req.requires_cookies,
            )
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return PlaylistOut(
            name=p.name, url=p.url, format=p.format, quality=p.quality,
            relative_path=p.relative_path, last_sync=p.last_sync,
            track_count=p.track_count, requires_cookies=p.requires_cookies,
        )

    @r.put("/playlists/{idx}", response_model=PlaylistOut)
    async def update_playlist(idx: int, req: UpdatePlaylistRequest) -> PlaylistOut:
        p = await app.library.update_playlist_by_idx(
            idx, name=req.name, url=req.url, fmt=req.format,
            quality=req.quality, requires_cookies=req.requires_cookies,
        )
        if p is None:
            raise HTTPException(404, f"playlist index {idx} out of range")
        return PlaylistOut(
            name=p.name, url=p.url, format=p.format, quality=p.quality,
            relative_path=p.relative_path, last_sync=p.last_sync,
            track_count=p.track_count, requires_cookies=p.requires_cookies,
        )

    @r.delete("/playlists/{idx}", response_model=SimpleOk)
    async def delete_playlist(idx: int, also_files: bool = False) -> SimpleOk:
        p = await app.library.remove_playlist_by_idx(idx, also_files=also_files)
        if p is None:
            raise HTTPException(404, f"playlist index {idx} out of range")
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
