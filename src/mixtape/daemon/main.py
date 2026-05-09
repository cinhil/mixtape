"""Daemon entry point.

  $ mixtape --daemon            # runs in foreground (systemd Type=simple)
  $ mixtape --daemon --port N   # explicit port (testing)

Default port: kernel-picked ephemeral. Token: 256-bit, freshly minted
each start.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

import uvicorn
from fastapi import FastAPI

from ..services import Application
from .auth import TOKEN
from .bootstrap import (
    DaemonInfo,
    clear_daemon_info,
    new_token,
    now_ts,
    pick_free_port,
    write_daemon_info,
)
from .events import make_events_router
from .lifespan import install_shutdown_event, request_shutdown, shutdown_event
from .routes import make_router


log = logging.getLogger("mixtape.daemon")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="mixtape --daemon")
    p.add_argument("--port", type=int, default=0, help="Bind port (0 = ephemeral, default)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--log-level", default="info")
    return p.parse_args(argv)


def make_app(application: Application) -> FastAPI:
    api = FastAPI(
        title="mixtape daemon",
        version="0.1",
        docs_url="/docs",
        redoc_url=None,
    )
    api.include_router(make_router(application))
    api.include_router(make_events_router(application))
    return api


async def _serve(application: Application, host: str, port: int, log_level: str) -> None:
    api = make_app(application)
    config = uvicorn.Config(
        api, host=host, port=port,
        log_level=log_level,
        # Daemon owns the asyncio loop, so let uvicorn use it without
        # spawning its own (the default `asyncio` loop is fine; we
        # don't ask for `uvloop` to avoid an extra dep on Windows).
        loop="asyncio",
        # No access log — chatty for a single-user daemon.
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="uvicorn")
    # Wait either for shutdown signal OR uvicorn to exit on its own.
    shut = shutdown_event()
    assert shut is not None
    shut_task = asyncio.create_task(shut.wait(), name="shutdown-waiter")
    done, pending = await asyncio.wait(
        [server_task, shut_task], return_when=asyncio.FIRST_COMPLETED,
    )
    if shut_task in done:
        log.info("shutdown signal received, asking uvicorn to exit")
        server.should_exit = True
        await server_task
    for t in pending:
        t.cancel()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    def _on_signal(signame: str) -> None:
        log.info("signal %s received", signame)
        request_shutdown()

    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _on_signal, sig.name)
    else:
        # Windows asyncio doesn't support add_signal_handler — use the
        # blocking signal module hooks. CTRL_BREAK / CTRL_C reach us
        # because the daemon is detached but in its own process group.
        signal.signal(signal.SIGINT, lambda *_: request_shutdown())
        try:
            signal.signal(signal.SIGBREAK, lambda *_: request_shutdown())  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


async def amain(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    application = Application()
    await application.start()

    # Install shutdown plumbing.
    shut_evt = asyncio.Event()
    install_shutdown_event(shut_evt)
    _install_signal_handlers(asyncio.get_running_loop())

    # Mint a token + pick a port.
    port = args.port if args.port > 0 else pick_free_port(args.host)
    token = new_token()
    TOKEN.set(token)

    info = DaemonInfo(
        pid=os.getpid(), port=port, token=token,
        host=args.host, started_at=now_ts(),
    )
    write_daemon_info(info)
    try:
        await _serve(application, args.host, port, args.log_level)
    finally:
        log.info("daemon stopping")
        await application.stop()
        clear_daemon_info()
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130
