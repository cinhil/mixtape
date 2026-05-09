from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml
from yt_dlp.utils import sanitize_filename

AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".flac", ".ogg", ".webm"}


@dataclass
class Track:
    number: int
    title: str = ""
    filename: str = ""  # last known filename on disk


@dataclass
class Manifest:
    """Per-playlist state stored next to the audio files.

    Carries enough info (url, name, format, quality, requires_cookies) to
    reconstruct the Playlist definition on a different machine. So a USB
    device with a `.mixtape` library marker + per-playlist `.manifest.yaml`
    files is fully self-describing — any mixtape installation can re-import
    everything from it.
    """
    tracks: dict[str, Track] = field(default_factory=dict)  # video_id -> Track
    # Playlist-level fields
    url: str = ""
    name: str = ""
    format: str = ""
    quality: str = ""
    requires_cookies: bool = True
    last_sync: str | None = None

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text()) or {}
        raw = data.get("tracks") or {}
        tracks = {vid: Track(**t) for vid, t in raw.items()}
        return cls(
            tracks=tracks,
            url=str(data.get("url", "") or ""),
            name=str(data.get("name", "") or ""),
            format=str(data.get("format", "") or ""),
            quality=str(data.get("quality", "") or ""),
            requires_cookies=bool(data.get("requires_cookies", True)),
            last_sync=data.get("last_sync") or None,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "url": self.url,
            "name": self.name,
            "format": self.format,
            "quality": self.quality,
            "requires_cookies": self.requires_cookies,
            "last_sync": self.last_sync,
            "tracks": {vid: asdict(t) for vid, t in self.tracks.items()},
        }
        path.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))

    def assign(self, video_id: str, title: str) -> int:
        """Return existing number for video_id, or assign next available."""
        if video_id in self.tracks:
            t = self.tracks[video_id]
            if title and not t.title:
                t.title = title
            return t.number
        n = (max((t.number for t in self.tracks.values()), default=0)) + 1
        self.tracks[video_id] = Track(number=n, title=title)
        return n

    def padding(self) -> int:
        """Min digits needed for current track count, at least 3."""
        n = max((t.number for t in self.tracks.values()), default=1)
        return max(3, len(str(n)))


def expected_prefix(number: int, pad: int) -> str:
    return f"{number:0{pad}d} - "


def migrate_filenames(out_dir: Path, manifest: Manifest, pad: int) -> list[tuple[str, str]]:
    """Rename files in out_dir to match canonical numbering.

    Handles:
    - Pre-manifest files like "NA - Artist - Title.mp3"
    - Renumbering when padding grows (e.g. 99 → 100 tracks)
    - YouTube playlist reorders (number changes — file moves to new prefix)

    Two-pass with temp suffix so that circular renames (e.g. A↔B swap) work
    without collisions. Returns list of (old, new) renames performed.
    """
    if not out_dir.exists():
        return []
    files = [f for f in out_dir.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS]

    # Phase 1 — figure out the rename plan
    plan: list[tuple[Track, Path, str]] = []  # (track, src, target_name)
    for _, track in manifest.tracks.items():
        prefix = expected_prefix(track.number, pad)
        # Already correct?
        if track.filename and track.filename.startswith(prefix) and (out_dir / track.filename).exists():
            continue

        # Find the on-disk file: stored filename, or by sanitized title match.
        candidate: Path | None = None
        if track.filename and (out_dir / track.filename).exists():
            candidate = out_dir / track.filename
        elif track.title:
            sanitized = sanitize_filename(track.title, restricted=False)
            matches = [f for f in files if sanitized.lower() in f.name.lower()]
            if len(matches) == 1:
                candidate = matches[0]
        if not candidate:
            continue
        if candidate.name.startswith(prefix):
            track.filename = candidate.name
            continue

        # Build the target filename: replace the leading "<old-prefix> - " with the new one.
        stem = candidate.stem
        parts = stem.split(" - ", 1)
        rest = parts[1] if len(parts) == 2 else stem
        target_name = f"{prefix}{rest}{candidate.suffix}"
        if target_name == candidate.name:
            track.filename = candidate.name
            continue
        plan.append((track, candidate, target_name))

    if not plan:
        return []

    # Phase 2 — move all sources to temp names so circular swaps don't collide.
    TEMP_SUFFIX = ".__rename__"
    staged: list[tuple[Track, Path, str, str]] = []  # (track, temp, target_name, original_name)
    for track, src, target_name in plan:
        temp_path = src.with_name(src.name + TEMP_SUFFIX)
        try:
            src.rename(temp_path)
        except OSError:
            continue
        staged.append((track, temp_path, target_name, src.name))

    # Phase 3 — temp → final.
    renames: list[tuple[str, str]] = []
    for track, temp_path, target_name, original_name in staged:
        target_path = temp_path.parent / target_name
        if target_path.exists():
            # An orphan blocks us — revert this one to the original.
            try:
                temp_path.rename(temp_path.parent / original_name)
            except OSError:
                pass
            continue
        try:
            temp_path.rename(target_path)
        except OSError:
            continue
        track.filename = target_name
        renames.append((original_name, target_name))

    return renames
