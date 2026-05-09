"""Check whether mixtape itself has an update available.

Behaviour depends on the install channel — auto-detected from the local git
state (no config required):

- **dev**     : HEAD is on a branch (e.g. ``main``). Update = local commit
                is behind ``origin/<branch>`` HEAD.
- **stable**  : HEAD is at a tag (e.g. ``v0.1.0b1``). Update = a newer
                release tag exists on GitHub.

Cached for 1 hour to avoid hammering GitHub or the git remote.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


CACHE_TTL = 3600.0  # 1 hour
GITHUB_API = "https://api.github.com/repos/cinhil/mixtape/releases/latest"


@dataclass
class UpdateStatus:
    channel: Literal["dev", "stable", "unknown"]
    current: str  # e.g. "v0.1.0b1" or short commit hash
    latest: str  # what's available upstream (same kind as current)
    behind: bool  # True if there's a newer thing
    message: str  # human-readable
    checked_at: float = 0.0

    @property
    def has_update(self) -> bool:
        return self.behind


_cache: UpdateStatus | None = None


def _find_repo_dir() -> Path | None:
    """Walk up from this module's path looking for a .git directory.
    Works whether mixtape is installed editable (most common via uv sync) or
    bundled — in the latter case repo isn't there and we return None."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / ".git").exists():
            return ancestor
    return None


def _git(repo: Path, *args: str, timeout: float = 10.0) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _do_check() -> UpdateStatus | None:
    repo = _find_repo_dir()
    if not repo:
        return None  # not running from a git checkout — no update notion

    # Branch we're on (if any) — empty string if HEAD is detached (i.e. on a tag).
    branch = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD") or ""

    if branch:
        return _check_dev(repo, branch)

    # Detached HEAD — try to identify which tag points here.
    tag = _git(repo, "describe", "--tags", "--exact-match")
    if tag:
        return _check_stable(repo, tag)

    # Detached but not on a tag → unusual; report as dev with commit hash.
    return _check_dev(repo, "HEAD")


def _check_dev(repo: Path, branch: str) -> UpdateStatus:
    # Quick, low-bandwidth fetch (refs only).
    _git(repo, "fetch", "--quiet", "origin", branch, timeout=15.0)
    local = _git(repo, "rev-parse", "--short", "HEAD") or "?"
    upstream = (
        _git(repo, "rev-parse", "--short", f"origin/{branch}") or local
    )
    if local == upstream:
        return UpdateStatus(
            channel="dev", current=local, latest=upstream,
            behind=False, message=f"on {branch}, up to date ({local})",
        )
    # Count how many commits we're behind
    behind_count = _git(repo, "rev-list", "--count", f"HEAD..origin/{branch}") or "?"
    return UpdateStatus(
        channel="dev", current=local, latest=upstream, behind=True,
        message=f"on {branch}, {behind_count} commit(s) behind ({local} → {upstream})",
    )


def _check_stable(repo: Path, current_tag: str) -> UpdateStatus:
    latest_tag = _fetch_latest_release_tag()
    if not latest_tag:
        return UpdateStatus(
            channel="stable", current=current_tag, latest=current_tag,
            behind=False, message=f"on {current_tag} (couldn't reach GitHub for latest release)",
        )
    if latest_tag == current_tag:
        return UpdateStatus(
            channel="stable", current=current_tag, latest=latest_tag,
            behind=False, message=f"on {current_tag}, latest release",
        )
    return UpdateStatus(
        channel="stable", current=current_tag, latest=latest_tag, behind=True,
        message=f"on {current_tag}, newer release available: {latest_tag}",
    )


def _fetch_latest_release_tag() -> str | None:
    try:
        with urllib.request.urlopen(GITHUB_API, timeout=5) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError):
        return None
    return data.get("tag_name") or None


def get_update_status(force: bool = False) -> UpdateStatus | None:
    """Return cached status if recent enough, else re-check. None if not in a git checkout."""
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache.checked_at) < CACHE_TTL:
        return _cache
    status = _do_check()
    if status is not None:
        status.checked_at = now
        _cache = status
    return status


def invalidate_cache() -> None:
    global _cache
    _cache = None
