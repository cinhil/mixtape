"""Daemon client — handles discovery, auto-launch, REST calls, WS event
stream. The TUI and the desktop UI both use this; neither imports the
services directly.

Design notes
------------
- The daemon's ``api.json`` is the source of truth for connection.
  We don't probe ports or guess. If the file is missing or its PID
  is dead, we (best-effort) spawn the daemon and retry.
- HTTP and WS share the same bearer token.
- On disconnect the WS iterator just exits; callers re-call
  ``events()`` to reconnect (or use ``stream_events_forever``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import websockets
from websockets.exceptions import ConnectionClosed


from ..daemon.bootstrap import (
    DaemonInfo,
    daemon_pid_alive,
    read_daemon_info,
)


log = logging.getLogger("mixtape.client")


class DaemonError(RuntimeError):
    """Generic remote error (HTTP non-2xx, etc.)."""


class DaemonNotRunning(DaemonError):
    """Could not connect to a daemon and could not start one."""


class DaemonClient:
    def __init__(self, info: DaemonInfo, http: httpx.AsyncClient) -> None:
        self._info = info
        self._http = http

    # ── lifecycle ──────────────────────────────────────────────────────

    @classmethod
    async def connect(cls, *, autostart: bool = True,
                      max_attempts: int = 30,
                      backoff_s: float = 0.2) -> "DaemonClient":
        """Discover a running daemon, optionally spawning one if absent.
        Polls the HTTP /status endpoint until it's reachable; gives up
        after ``max_attempts * backoff_s`` seconds."""
        info = read_daemon_info()
        if info is None or not daemon_pid_alive(info.pid):
            if not autostart:
                raise DaemonNotRunning("no daemon running and autostart disabled")
            _spawn_daemon()
            for _ in range(max_attempts):
                await asyncio.sleep(backoff_s)
                info = read_daemon_info()
                if info is not None and daemon_pid_alive(info.pid):
                    break
            else:
                raise DaemonNotRunning("daemon did not come up in time")

        # api.json is fresh; now poll for the HTTP port to actually bind.
        http = httpx.AsyncClient(
            base_url=info.base_url,
            headers={"Authorization": f"Bearer {info.token}"},
            timeout=httpx.Timeout(10.0, connect=2.0),
        )
        for _ in range(max_attempts):
            try:
                r = await http.get("/status")
                if r.status_code == 200:
                    return cls(info, http)
            except (httpx.ConnectError, httpx.ReadError):
                pass
            await asyncio.sleep(backoff_s)
        await http.aclose()
        raise DaemonNotRunning("daemon found but /status never responded")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "DaemonClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    # ── REST ──────────────────────────────────────────────────────────

    async def status(self) -> dict[str, Any]:
        return await self._json("GET", "/status")

    async def libraries(self) -> dict[str, Any]:
        return await self._json("GET", "/libraries")

    async def set_active_library(self, name: str) -> None:
        await self._json("POST", "/libraries/active", json={"library": name})

    async def set_close_to_tray(self, enabled: bool) -> None:
        await self._json("POST", "/libraries/close-to-tray", json={"enabled": enabled})

    async def playlists(self, library: str | None = None) -> list[dict[str, Any]]:
        if library is None:
            return await self._json("GET", "/playlists")
        return await self._json("GET", f"/libraries/{library}/playlists")

    async def sync(self, library: str | None = None,
                   playlists: list[int] | None = None) -> dict[str, Any]:
        return await self._json("POST", "/sync",
            json={"library": library, "playlists": playlists})

    async def cancel_sync(self) -> None:
        await self._json("POST", "/sync/cancel")

    async def refresh_cookies(self) -> None:
        await self._json("POST", "/cookies/refresh")

    async def set_cookies(self, content: str) -> dict[str, Any]:
        return await self._json("POST", "/cookies", json={"content": content})

    async def list_volumes(self) -> list[dict[str, Any]]:
        return await self._json("GET", "/volumes")

    async def add_library(self, name: str, path: str, *,
                          volume_name: str = "", auto_sync: bool = False,
                          uuid: str = "", create_marker: bool = False) -> None:
        await self._json("POST", "/libraries", json={
            "name": name, "path": path,
            "volume_name": volume_name, "auto_sync": auto_sync,
            "uuid": uuid, "create_marker": create_marker,
        })

    async def remove_library(self, name: str) -> None:
        await self._json("DELETE", f"/libraries/{name}")

    async def register_volume(self, mount_path: str, fallback_name: str | None = None) -> dict[str, Any]:
        return await self._json("POST", "/libraries/register-volume", json={
            "mount_path": mount_path, "fallback_name": fallback_name,
        })

    async def add_playlist(self, url: str, *,
                           name: str | None = None,
                           fmt: str | None = None,
                           quality: str | None = None,
                           requires_cookies: bool = True) -> dict[str, Any]:
        return await self._json("POST", "/playlists", json={
            "url": url, "name": name, "format": fmt, "quality": quality,
            "requires_cookies": requires_cookies,
        })

    async def update_playlist(self, idx: int, *,
                              name: str | None = None,
                              url: str | None = None,
                              fmt: str | None = None,
                              quality: str | None = None,
                              requires_cookies: bool | None = None) -> dict[str, Any]:
        return await self._json("PUT", f"/playlists/{idx}", json={
            "name": name, "url": url, "format": fmt, "quality": quality,
            "requires_cookies": requires_cookies,
        })

    async def delete_playlist(self, idx: int, also_files: bool = False) -> None:
        await self._json("DELETE", f"/playlists/{idx}", params={"also_files": str(also_files).lower()})

    async def refresh_update(self) -> None:
        await self._json("POST", "/update/refresh")

    async def apply_update(self) -> dict[str, Any]:
        return await self._json("POST", "/update/apply")

    async def shutdown(self) -> None:
        await self._json("POST", "/shutdown")

    # ── WS event stream ──────────────────────────────────────────────

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Async iterator over server events. Exits cleanly on
        disconnect — caller should re-call to reconnect, or use
        ``stream_events_forever`` for retry-with-backoff."""
        ws_url = self._info.base_url.replace("http://", "ws://", 1) + "/events"
        # Pass the token both as header AND query string for max
        # compatibility (browser WS clients can't set headers).
        headers = {"Authorization": f"Bearer {self._info.token}"}
        ws_url_with_token = ws_url + f"?token={self._info.token}"
        try:
            async with websockets.connect(ws_url_with_token, additional_headers=headers) as ws:
                while True:
                    try:
                        msg = await ws.recv()
                    except ConnectionClosed:
                        return
                    try:
                        yield json.loads(msg)
                    except json.JSONDecodeError:
                        log.warning("ignoring malformed event: %r", msg[:120])
        except (OSError, ConnectionClosed):
            return

    async def stream_events_forever(self, *,
                                    backoff_s: float = 1.0,
                                    backoff_max_s: float = 30.0) -> AsyncIterator[dict[str, Any]]:
        """Reconnecting event iterator. Yields events; on disconnect
        retries with exponential backoff (capped). Exits only when
        cancelled."""
        delay = backoff_s
        while True:
            connected = False
            async for ev in self.events():
                connected = True
                delay = backoff_s  # reset after a successful event
                yield ev
            if connected is False:
                # Connection failed before any event; back off harder.
                await asyncio.sleep(delay)
                delay = min(delay * 2, backoff_max_s)
            else:
                await asyncio.sleep(backoff_s)

    # ── internal ─────────────────────────────────────────────────────

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            r = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise DaemonError(f"transport error: {e}") from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise DaemonError(f"{method} {path} → {r.status_code}: {detail}")
        if r.status_code == 204 or not r.content:
            return None
        return r.json()


def _spawn_daemon() -> None:
    """Spawn ``mixtape-daemon`` (or ``python -m mixtape.daemon.main``)
    detached from the current console. Best-effort — caller polls for
    api.json afterwards."""
    cmd = _daemon_cmd()
    log.info("spawning daemon: %s", cmd)
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        popen_kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **popen_kwargs)
    except OSError as e:
        log.warning("daemon spawn failed: %s", e)


def _daemon_cmd() -> list[str]:
    """Build the command vector for spawning the daemon. Prefer the
    pythonw/python next to the current interpreter so we run inside
    the venv even if PATH doesn't have it."""
    if sys.platform == "win32":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            return [str(pythonw), "-m", "mixtape.daemon.main"]
        return [sys.executable, "-m", "mixtape.daemon.main"]
    # Try the project script first (pip-installed `mixtape-daemon`),
    # else fall back to `python -m`.
    import shutil
    on_path = shutil.which("mixtape-daemon")
    if on_path:
        return [on_path]
    return [sys.executable, "-m", "mixtape.daemon.main"]
