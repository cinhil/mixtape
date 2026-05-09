"""``.mixtape`` marker file at a library root.

The marker turns a folder on any disk into a *recognisable* mixtape library:
when the user plugs the device into a different machine (or after a fresh
mixtape install), the volume watcher finds the marker and recognises the
library by its stable UUID — independently of the volume label, drive
letter, or device node.

File format (YAML):

    # mixtape library — do not delete
    uuid: 7f3a2b8c-4d5e-6789-…
    name: USB MP3 Player
    created: 2026-05-09T00:12:34
    mixtape_version: 0.1.0b1
    auto_sync: true
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import yaml


MARKER_FILENAME = ".mixtape"

# Subfolders to scan when probing a freshly-plugged volume for a marker.
# We try the root first, then a "music" / "Music" subdir (common on USB MP3
# players where the player groups everything under a top folder).
PROBE_SUBPATHS = ("", "music", "Music", "MUSIC")


@dataclass
class LibraryMarker:
    uuid: str
    name: str
    created: str = ""
    mixtape_version: str = ""
    auto_sync: bool = True

    @classmethod
    def new(cls, name: str, *, auto_sync: bool = True, mixtape_version: str = "") -> "LibraryMarker":
        return cls(
            uuid=str(uuid.uuid4()),
            name=name,
            created=datetime.now().isoformat(timespec="seconds"),
            mixtape_version=mixtape_version,
            auto_sync=auto_sync,
        )


def read_marker(library_root: Path) -> LibraryMarker | None:
    """Read .mixtape from `library_root`, or None if absent / malformed."""
    marker_file = library_root / MARKER_FILENAME
    if not marker_file.is_file():
        return None
    try:
        data = yaml.safe_load(marker_file.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return None
    uid = data.get("uuid")
    name = data.get("name") or ""
    if not uid:
        return None
    return LibraryMarker(
        uuid=str(uid),
        name=str(name),
        created=str(data.get("created", "")),
        mixtape_version=str(data.get("mixtape_version", "")),
        auto_sync=bool(data.get("auto_sync", True)),
    )


def write_marker(library_root: Path, marker: LibraryMarker) -> None:
    library_root.mkdir(parents=True, exist_ok=True)
    payload = (
        "# mixtape library — do not delete (used to recognise this library "
        "across machines)\n"
        + yaml.safe_dump(asdict(marker), sort_keys=False, allow_unicode=True)
    )
    (library_root / MARKER_FILENAME).write_text(payload)


def find_marker_on_volume(volume_mount: Path) -> tuple[LibraryMarker, Path] | None:
    """Probe a volume for a .mixtape marker. Returns (marker, root_dir)."""
    for sub in PROBE_SUBPATHS:
        candidate_root = volume_mount / sub if sub else volume_mount
        if not candidate_root.is_dir():
            continue
        m = read_marker(candidate_root)
        if m is not None:
            return m, candidate_root
    return None


def discover_playlists(library_root: Path) -> list[dict]:
    """Enumerate playlist subdirs of a library root and return their metadata
    (read from each subdir's `.manifest.yaml`). One dict per playlist with the
    keys ``url``, ``name``, ``format``, ``quality``, ``requires_cookies``,
    ``relative_path``, plus a count of tracks. Skips subdirs without a
    manifest or without a recoverable URL."""
    if not library_root.is_dir():
        return []
    out: list[dict] = []
    # Local import to avoid a circular config <-> manifest dance at module load.
    from .manifest import Manifest
    for sub in sorted(p for p in library_root.iterdir() if p.is_dir()):
        manifest_path = sub / ".manifest.yaml"
        if not manifest_path.is_file():
            continue
        m = Manifest.load(manifest_path)
        if not m.url:
            continue  # legacy manifest predating the playlist-level fields
        out.append({
            "url": m.url,
            "name": m.name or sub.name,
            "format": m.format or "mp3",
            "quality": m.quality or "0",
            "requires_cookies": m.requires_cookies,
            "relative_path": sub.name,
            "track_count": len(m.tracks),
        })
    return out
