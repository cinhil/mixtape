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


class SetCookiesRequest(BaseModel):
    content: str  # raw Netscape cookies.txt content


class CookieStatusOut(BaseModel):
    state: str
    message: str
    ok: bool = False


class AddLibraryRequest(BaseModel):
    name: str
    path: str
    volume_name: str = ""
    auto_sync: bool = False
    uuid: str = ""
    create_marker: bool = False  # write a .mixtape marker into ``path``


class RegisterVolumeRequest(BaseModel):
    mount_path: str
    fallback_name: str | None = None


class RegisterVolumeResult(BaseModel):
    name: str
    path: str
    uuid: str
    created: bool


class AddPlaylistRequest(BaseModel):
    url: str
    name: str | None = None
    format: str | None = None
    quality: str | None = None
    requires_cookies: bool = True


class UpdatePlaylistRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    format: str | None = None
    quality: str | None = None
    requires_cookies: bool | None = None


class VolumeOut(BaseModel):
    identifier: str
    label: str
    mount_path: str
    fs_type: str
    size_bytes: int
    free_bytes: int
    is_removable: bool
    marker: dict[str, Any] | None = None
