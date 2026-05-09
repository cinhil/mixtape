"""Tiny CLI helpers for headless / SSH workflows.

The TUI is the main interface, but a headless RPi user can't press 'c' to
update cookies. ``mixtape --set-cookies`` reads cookies from stdin so the
user can pipe them in via SSH:

    ssh pi@rpi 'mixtape --set-cookies' < cookies.txt
"""
from __future__ import annotations

import sys

from .config import COOKIES_FILE, write_cookies
from .cookies_check import get_cookie_status, invalidate_cache


def set_cookies_from_stdin() -> int:
    if sys.stdin.isatty():
        sys.stderr.write(
            "mixtape --set-cookies expects the Netscape cookies.txt content on stdin.\n"
            "Example:  ssh pi@rpi 'mixtape --set-cookies' < cookies.txt\n"
        )
        return 2
    text = sys.stdin.read()
    if not text.strip():
        sys.stderr.write("Empty input — refusing to overwrite cookies file.\n")
        return 1
    if "youtube" not in text.lower() and not text.lstrip().startswith("# Netscape"):
        sys.stderr.write(
            "Input doesn't look like a Netscape cookies.txt for YouTube — refusing.\n"
            "Use the 'Get cookies.txt LOCALLY' browser extension on music.youtube.com.\n"
        )
        return 1
    write_cookies(text + ("\n" if not text.endswith("\n") else ""))
    sys.stdout.write(f"Cookies written to {COOKIES_FILE}.\n")

    # Re-validate immediately so the user gets an answer in the same SSH call.
    invalidate_cache()
    status = get_cookie_status(force=True)
    if status.ok:
        sys.stdout.write(f"✓ Cookies valid — {status.message}\n")
        # If a marker file was set by the headless service, clear it.
        try:
            from .headless import NEEDS_COOKIES_MARKER
            if NEEDS_COOKIES_MARKER.exists():
                NEEDS_COOKIES_MARKER.unlink()
        except Exception:  # noqa: BLE001
            pass
        return 0
    sys.stderr.write(f"✗ Cookies look invalid: {status.message}\n")
    return 1
