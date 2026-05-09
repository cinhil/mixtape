"""Cookie validity check.

YouTube cookies expire roughly every month (LOGIN_INFO renewal). We need to
detect that quickly and stop downloads, otherwise yt-dlp falls back to the
public quality tier silently.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import yt_dlp

from .config import cookies_path


CACHE_TTL = 300.0  # seconds — re-check at most once every 5 minutes


@dataclass
class CookieStatus:
    state: Literal["valid", "missing", "expired", "unknown"]
    message: str
    checked_at: float = 0.0

    @property
    def ok(self) -> bool:
        return self.state == "valid"


_cache: CookieStatus | None = None


def _do_check() -> CookieStatus:
    cp = cookies_path()
    if not cp:
        return CookieStatus(state="missing", message="no cookies file — paste cookies via 'c'")
    if not cp.exists():
        return CookieStatus(state="missing", message="cookies file disappeared")

    # Probe: list the user's saved playlists. /feed/playlists requires a
    # logged-in session — anonymous calls return zero entries or 4xx.
    opts = {
        "cookiefile": str(cp),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playlist_items": "1",  # one entry is enough to confirm auth
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info("https://www.youtube.com/feed/playlists", download=False) or {}
    except Exception as e:  # noqa: BLE001
        msg = str(e).split("\n")[0]
        if "Sign in" in msg or "log in" in msg.lower() or "not logged" in msg.lower():
            return CookieStatus(state="expired", message="not logged in — re-paste cookies via 'c'")
        return CookieStatus(state="unknown", message=msg[:120])

    entries = info.get("entries") or []
    if not entries:
        return CookieStatus(
            state="expired",
            message="playlists feed returned no items — cookies likely expired",
        )
    return CookieStatus(state="valid", message=f"logged in ({len(entries)}+ playlists visible)")


def get_cookie_status(force: bool = False) -> CookieStatus:
    """Return cached status if recent enough, else re-check."""
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache.checked_at) < CACHE_TTL:
        return _cache
    status = _do_check()
    status.checked_at = now
    _cache = status
    return status


def invalidate_cache() -> None:
    """Force the next get_cookie_status() to do a fresh check."""
    global _cache
    _cache = None
