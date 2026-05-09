"""Smoke tests for the service layer."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point XDG_* dirs at tmp_path so we don't touch the user's real
    config / state. Reload mixtape.config so its module-level paths
    pick up the new env."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    import mixtape.config as cfg_mod
    importlib.reload(cfg_mod)
    return tmp_path


def test_event_bus_publishes_to_subscribers():
    from mixtape.services import EventBus

    async def run():
        bus = EventBus()
        async with bus.subscribe() as q:
            bus.publish("daemon.ready", pid=1, started_at=0.0)
            ev = await asyncio.wait_for(q.get(), timeout=1)
            assert ev.name == "daemon.ready"
            assert ev.data["pid"] == 1

    asyncio.run(run())


def test_application_constructs(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path)
    from mixtape.services import Application
    app = Application()
    # All services attached.
    for name in ("bus", "library", "bgutil", "watcher",
                 "cookies", "updates", "sync", "volumes"):
        assert hasattr(app, name), f"missing {name}"
    # Library service finds (or creates) the default PC library.
    snap = asyncio.run(app.library.snapshot())
    assert snap["active"]
    assert any(lib["name"] == snap["active"] for lib in snap["libraries"])


def test_library_service_add_remove(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path)
    from mixtape.services import Application

    async def run():
        app = Application()
        new_path = tmp_path / "extra-lib"
        new_path.mkdir()
        await app.library.add_library(name="Extra", path=str(new_path), create_marker=True)
        snap = await app.library.snapshot()
        names = [lib["name"] for lib in snap["libraries"]]
        assert "Extra" in names
        # Marker was written (has_marker=True).
        marker = new_path / ".mixtape"
        assert marker.is_file(), "create_marker=True should have written .mixtape"
        # Removable.
        await app.library.remove_library("Extra")
        snap2 = await app.library.snapshot()
        assert "Extra" not in [lib["name"] for lib in snap2["libraries"]]

    asyncio.run(run())


def test_cookie_service_rejects_garbage(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path)
    from mixtape.services import Application

    async def run():
        app = Application()
        with pytest.raises(ValueError):
            await app.cookies.write("not even close to a cookies.txt")

    asyncio.run(run())


def test_watcher_service_starts_and_stops(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path)
    from mixtape.services import Application

    async def run():
        app = Application()
        await app.watcher.start()
        await asyncio.sleep(0.1)  # let the polling thread settle
        await app.watcher.stop()

    asyncio.run(run())
