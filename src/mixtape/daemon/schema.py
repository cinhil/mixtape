"""Pydantic models for the daemon's REST surface.

Importable by Python clients (TUI / Qt UI) so types match end-to-end.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DaemonStatus(BaseModel):
    pid: int
    started_at: float
    version: str = "0.1"
    bgutil: dict[str, Any] = Field(default_factory=dict)
    cookies: dict[str, Any] = Field(default_factory=dict)
    update: dict[str, Any] | None = None
    sync_in_progress: bool = False


class LibrarySnapshot(BaseModel):
    active: str
    libraries: list[dict[str, Any]]
    close_to_tray: bool = False


class PlaylistOut(BaseModel):
    name: str
    url: str
    format: str
    quality: str
    relative_path: str
    last_sync: str | None
    track_count: int
    requires_cookies: bool


class SyncRequest(BaseModel):
    library: str | None = None  # default = active
    playlists: list[int] | None = None  # default = all


class SyncResponse(BaseModel):
    ok: bool
    cancelled: bool
    library: str
    synced: int
    reason: str | None = None


class SetActiveRequest(BaseModel):
    library: str


class SetCloseToTrayRequest(BaseModel):
    enabled: bool


class UpdateApplyResult(BaseModel):
    ok: bool
    message: str


class SimpleOk(BaseModel):
    ok: bool = True
