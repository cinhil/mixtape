"""Headless / daemon mode — no TUI, just plain logs.

Designed for a Raspberry Pi (or any always-on machine) running as a systemd
service. Behaviour:
- Watches for USB volumes (cross-platform via platform_io).
- When a registered Library's volume_name appears, switches active and
  auto-syncs all playlists to it.
- After sync, flushes the filesystem and prints "safe to unplug".
- Cookies must be valid; otherwise the sync is skipped with a clear log line.
"""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from .bgutil_server import BgutilServer
from .config import Config, Library, Playlist
from .cookies_check import get_cookie_status
from .downloader import ProgressEvent, sync_playlist
from .platform_io import VolumeChange, VolumeWatcher, flush_filesystem, platform_name


log = logging.getLogger("mixtape")


def run_headless() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    cfg = Config.load()
    log.info("mixtape headless — platform=%s", platform_name())
    log.info(
        "loaded: %d libraries, %d playlists; active=%r",
        len(cfg.libraries), len(cfg.playlists), cfg.active_library,
    )
    if not cfg.playlists:
        log.warning("no playlists configured — start the TUI once to add some")

    # Cookies must be valid before we ever try a download.
    cs = get_cookie_status(force=True)
    log.info("cookie status: state=%s — %s", cs.state, cs.message)
    if not cs.ok:
        log.warning("cookies invalid — auto-sync will be skipped until you re-paste them")

    # Spin up the bgutil companion daemon (best effort — optional).
    bgutil = BgutilServer()
    ok, msg = bgutil.start()
    log.info("bgutil server: %s — %s", "ok" if ok else "fail", msg)

    sync_lock = threading.Lock()  # one sync at a time
    stop_event = threading.Event()

    def on_change(change: VolumeChange) -> None:
        if change.removed:
            log.info("volumes removed: %s", change.removed)
        for vol in change.added:
            log.info(
                "volume added: %s [%s] @ %s (%s, %s)",
                vol.identifier, vol.label, vol.mount_path, vol.fs_type,
                "removable" if vol.is_removable else "fixed",
            )
            lib = next(
                (lib for lib in cfg.libraries if lib.volume_name and lib.volume_name == vol.label),
                None,
            )
            if not lib:
                log.info("  → not a registered library, ignoring")
                continue
            log.info("  → registered as library %r", lib.name)
            # Refresh cookies before syncing
            fresh = get_cookie_status(force=True)
            if not fresh.ok:
                log.warning("  → cookies %s (%s) — skipping sync", fresh.state, fresh.message)
                continue
            cfg.set_active_library(lib.name)
            if lib.auto_sync and cfg.playlists:
                threading.Thread(
                    target=_run_sync, args=(cfg, lib, sync_lock), daemon=True,
                ).start()
            else:
                log.info("  → auto-sync disabled or no playlists — nothing to do")

    watcher = VolumeWatcher(on_change)
    watcher.start()

    # Graceful shutdown on SIGTERM (systemd) / SIGINT (ctrl-c)
    def _stop(signum, _frame):
        log.info("signal %s received — shutting down", signum)
        stop_event.set()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info("watching for USB devices… (poll interval ~5s)")
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        watcher.stop()
        bgutil.stop()
        log.info("bye")
    return 0


def _run_sync(cfg: Config, library: Library, lock: threading.Lock) -> None:
    if not lock.acquire(blocking=False):
        log.info("a sync is already running — queue rejected")
        return
    try:
        log.info("starting auto-sync of %d playlists → %r (%s)",
                 len(cfg.playlists), library.name, library.path)
        for i, pl in enumerate(cfg.playlists):
            try:
                _sync_one(pl, library, i)
                cfg.mark_synced(i, pl.track_count)
            except Exception as e:  # noqa: BLE001
                log.error("playlist %r failed: %s", pl.name, e)
        try:
            flush_filesystem()
        except Exception:
            pass
        log.info("✓ auto-sync done — %r is safe to unplug", library.name)
    finally:
        lock.release()


def _sync_one(playlist: Playlist, library: Library, idx: int) -> None:
    def on_event(ev: ProgressEvent) -> None:
        if ev.kind == "start":
            log.info("  ▶ %s", ev.message)
        elif ev.kind == "done":
            log.info("  ✔ %s", ev.message)
        elif ev.kind == "cancelled":
            log.warning("  ⏹ %s", ev.message)
        elif ev.kind == "log":
            # Strip rich markup for plain log
            import re
            clean = re.sub(r"\[/?[^\]]+\]", "", ev.message)
            log.info("    %s", clean)

    sync_playlist(playlist, library, idx, on_event)


def main() -> int:  # entry point for `mixtape --headless`
    return run_headless()


if __name__ == "__main__":
    sys.exit(main())
