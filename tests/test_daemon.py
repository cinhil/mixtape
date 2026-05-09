"""Daemon-and-clients integration tests.

Boots a real daemon (with isolated XDG_* paths so it doesn't touch the
user's real config) and exercises the REST + WS surface via
DaemonClient. End-to-end: the same code path real clients use."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    # Reload so config / daemon modules pick up new XDG paths.
    import importlib
    import mixtape.config as cfg_mod
    importlib.reload(cfg_mod)
    import mixtape.daemon.bootstrap as bs_mod
    importlib.reload(bs_mod)
    return tmp_path


async def _start_daemon_inproc():
    """Run amain in the same loop as a Task; return the task + the
    DaemonInfo once api.json appears."""
    from mixtape.daemon.main import amain, parse_args
    from mixtape.daemon.bootstrap import read_daemon_info
    args = parse_args(["--port", "0", "--log-level", "warning"])
    task = asyncio.create_task(amain(args), name="daemon")
    for _ in range(60):
        info = read_daemon_info()
        if info is not None:
            return task, info
        await asyncio.sleep(0.1)
    task.cancel()
    raise AssertionError("daemon never wrote api.json")


def test_daemon_status_endpoint(isolated_env):
    async def run():
        from mixtape.client import DaemonClient
        task, info = await _start_daemon_inproc()
        try:
            client = DaemonClient(info, __import__("httpx").AsyncClient(
                base_url=info.base_url,
                headers={"Authorization": f"Bearer {info.token}"},
                timeout=__import__("httpx").Timeout(5.0, connect=2.0),
            ))
            # Wait for HTTP to come up.
            for _ in range(50):
                try:
                    s = await client.status()
                    break
                except Exception:
                    await asyncio.sleep(0.1)
            assert s["pid"] > 0
            assert "bgutil" in s and "cookies" in s
            await client.shutdown()
            await client.aclose()
        finally:
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.TimeoutError:
                task.cancel()
    asyncio.run(run())


def test_daemon_unauthorized(isolated_env):
    async def run():
        import httpx
        from mixtape.daemon.main import amain, parse_args
        from mixtape.daemon.bootstrap import read_daemon_info
        task = asyncio.create_task(amain(parse_args(["--port", "0", "--log-level", "warning"])))
        info = None
        try:
            for _ in range(60):
                info = read_daemon_info()
                if info is not None: break
                await asyncio.sleep(0.1)
            assert info is not None
            async with httpx.AsyncClient(base_url=info.base_url, timeout=5) as c:
                # poll until uvicorn binds
                for _ in range(30):
                    try:
                        r = await c.get("/status")
                        break
                    except (httpx.ConnectError, httpx.ReadError):
                        await asyncio.sleep(0.1)
                assert r.status_code == 401
                # shutdown via authed call
                rs = await c.post("/shutdown",
                    headers={"Authorization": f"Bearer {info.token}"})
                assert rs.status_code == 200
        finally:
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.TimeoutError:
                task.cancel()
    asyncio.run(run())


def test_daemon_event_stream(isolated_env):
    async def run():
        from mixtape.client import DaemonClient
        import httpx
        task, info = await _start_daemon_inproc()
        try:
            http = httpx.AsyncClient(base_url=info.base_url,
                headers={"Authorization": f"Bearer {info.token}"},
                timeout=httpx.Timeout(5.0, connect=2.0))
            client = DaemonClient(info, http)
            # poll until ready
            for _ in range(50):
                try:
                    await client.status()
                    break
                except Exception:
                    await asyncio.sleep(0.1)
            received = []
            async def reader():
                async for ev in client.events():
                    received.append(ev)
                    if len(received) >= 2:
                        return
            r = asyncio.create_task(reader())
            await asyncio.sleep(0.2)
            await client.refresh_cookies()
            try:
                await asyncio.wait_for(r, timeout=4)
            except asyncio.TimeoutError:
                r.cancel()
            assert any(ev.get("name") == "cookies.status" for ev in received)
            await client.shutdown()
            await client.aclose()
        finally:
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.TimeoutError:
                task.cancel()
    asyncio.run(run())
