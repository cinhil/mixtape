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
from .config import Config, Library, Playlist, STATE_DIR
from .cookies_check import get_cookie_status, invalidate_cache as invalidate_cookie_cache
from .downloader import ProgressEvent, sync_playlist
from .platform_io import VolumeChange, VolumeWatcher, flush_filesystem, platform_name


log = logging.getLogger("mixtape")

# Marker file the headless service touches when it discovers cookies are bad.
# Useful for any external monitoring (a shell prompt, a script, …) and for
# `mixtape --set-cookies` to know it can clear the alert.
NEEDS_COOKIES_MARKER = STATE_DIR / "needs-cookies"


def _set_needs_cookies(reason: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        NEEDS_COOKIES_MARKER.write_text(reason + "\n")
    except OSError:
        pass


def _clear_needs_cookies() -> None:
    try:
        if NEEDS_COOKIES_MARKER.exists():
            NEEDS_COOKIES_MARKER.unlink()
    except OSError:
        pass


def run_headless() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    cfg = Config.load()
    log.info("mixtape headless — platform=%s", platform_name())
    initial_pls = cfg.active_playlists()
    log.info(
        "loaded: %d libraries, %d playlists on active library %r",
        len(cfg.libraries), len(initial_pls), cfg.active_library,
    )
    if not initial_pls:
        log.warning("no playlists in active library — start the TUI once to add some")

    # Cookies must be valid before we ever try a download.
    cs = get_cookie_status(force=True)
    log.info("cookie status: state=%s — %s", cs.state, cs.message)
    if not cs.ok:
        log.warning("cookies invalid (%s) — auto-sync will be skipped", cs.state)
        log.warning(
            "to fix from another machine:  ssh <host> 'mixtape --set-cookies' < cookies.txt"
        )
        _set_needs_cookies(f"{cs.state}: {cs.message}")
    else:
        _clear_needs_cookies()

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
            cfg.set_active_library(lib.name)
            playlists = cfg.active_playlists()
            if not (lib.auto_sync and playlists):
                log.info("  → auto-sync disabled or no playlists — nothing to do")
                continue

            # Per-playlist cookie gate: which ones we can sync right now.
            invalidate_cookie_cache()
            fresh = get_cookie_status(force=True)
            cookie_ok = fresh.ok
            if cookie_ok:
                _clear_needs_cookies()
                targets = list(playlists)
            else:
                _set_needs_cookies(f"{fresh.state}: {fresh.message}")
                targets = [p for p in playlists if not p.requires_cookies]
                blocked = [p for p in playlists if p.requires_cookies]
                if blocked:
                    log.warning(
                        "  → cookies %s — skipping %d playlist(s) that require auth: %s",
                        fresh.state, len(blocked), ", ".join(p.name for p in blocked),
                    )
                    log.warning(
                        "    fix from another machine: ssh <host> 'mixtape --set-cookies' < cookies.txt",
                    )
                if not targets:
                    log.warning("  → no anonymous-mode playlists — nothing to sync")
                    continue
                log.info(
                    "  → syncing %d anonymous-mode playlist(s): %s",
                    len(targets), ", ".join(p.name for p in targets),
                )

            threading.Thread(
                target=_run_sync, args=(cfg, lib, targets, sync_lock), daemon=True,
            ).start()

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


def _run_sync(cfg: Config, library: Library, targets: list[Playlist], lock: threading.Lock) -> None:
    if not lock.acquire(blocking=False):
        log.info("a sync is already running — queue rejected")
        return
    try:
        log.info("starting auto-sync of %d playlist(s) → %r (%s)",
                 len(targets), library.name, library.path)
        for idx, pl in enumerate(targets):
            try:
                _sync_one(pl, library, idx)
                cfg.mark_synced(pl, pl.track_count)
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
