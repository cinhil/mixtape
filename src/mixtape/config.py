from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml


def _config_root() -> Path:
    """User config dir — XDG on Linux, %APPDATA% on Windows."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "mixtape"


def _data_root() -> Path:
    """User data dir — XDG on Linux, %LOCALAPPDATA% on Windows."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "mixtape"


def _state_root() -> Path:
    """User state dir — XDG on Linux, %LOCALAPPDATA%/state on Windows."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "mixtape" / "state"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "mixtape"


CONFIG_DIR = _config_root()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
COOKIES_FILE = CONFIG_DIR / "cookies.txt"

# Path of the optional bgutil-ytdlp-pot-provider companion (JS) — required by
# upstream yt-dlp changes since 2024 for full audio-format compatibility.
DATA_DIR = _data_root()
BGUTIL_SERVER_DIR = DATA_DIR / "bgutil-server"
STATE_DIR = _state_root()


def bgutil_server_path() -> Path | None:
    """Return the bgutil server dir if both the Deno script and node_modules
    are installed, else None (yt-dlp then operates without the companion)."""
    script = BGUTIL_SERVER_DIR / "src" / "generate_once.ts"
    node_modules = BGUTIL_SERVER_DIR / "node_modules"
    if script.exists() and node_modules.exists():
        return BGUTIL_SERVER_DIR
    return None


def slugify(name: str) -> str:
    """Folder-safe name from a playlist title — strips emojis/punctuation
    but keeps spaces. Public alias for the legacy ``_slugify``."""
    return _slugify(name)


def _slugify(name: str) -> str:
    """Folder-safe name from a playlist title — strips emojis/punctuation but
    keeps spaces (folders with spaces work fine on both Linux and NTFS)."""
    s = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip()
    s = re.sub(r"[\s_-]+", " ", s).strip()
    return s or "playlist"


@dataclass
class Library:
    """A music library = a folder with one subdir per playlist.

    Multiple libraries can coexist (e.g. PC drive + USB MP3 player). One is
    "active" at any moment — it determines where syncs read/write files.

    The optional ``uuid`` field (mirrored in a ``.mixtape`` marker file at the
    library root) is the stable identifier used to recognise a device across
    machines and even after a volume label change.
    """
    name: str
    path: str  # absolute path to the library root
    volume_name: str = ""  # Windows volume label, used as a fallback hint
    auto_sync: bool = False  # trigger sync automatically on USB plug-in
    uuid: str = ""  # matches the .mixtape marker; "" for legacy / local libs

    @property
    def root(self) -> Path:
        return Path(self.path).expanduser()

    @property
    def online(self) -> bool:
        """Is the library directory currently accessible? (USB devices may
        be unplugged.)"""
        return self.root.is_dir()


@dataclass
class Playlist:
    """A playlist's metadata. Lives on disk in
    ``<library>/<relative_path>/.manifest.yaml`` — never in the central
    config — so the device is fully self-describing."""
    name: str
    url: str
    format: str = "mp3"
    quality: str = "0"
    relative_path: str = ""  # subdir under library root; defaults to slug(name)
    last_sync: str | None = None
    track_count: int = 0
    requires_cookies: bool = True

    def expanded_dir_for(self, library: Library) -> Path:
        rel = self.relative_path or _slugify(self.name)
        return Path(library.path).expanduser() / rel

    def archive_file_for(self, library: Library) -> Path:
        return self.expanded_dir_for(library) / ".archive"


@dataclass
class Defaults:
    format: str = "mp3"
    quality: str = "0"


@dataclass
class Config:
    """Central config = cookies, libraries, defaults. Playlists themselves
    live on disk in each library — see ``playlists_for(library)``."""
    defaults: Defaults = field(default_factory=Defaults)
    active_library: str = "PC"
    libraries: list[Library] = field(default_factory=list)
    # When True, closing the TUI window spawns the system-tray daemon (so
    # USB plug/sync still works in the background). When False, closing
    # the window exits the app outright.
    close_to_tray: bool = False

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_FILE.exists():
            pc_path = Path.home() / "Music/mixtape"
            pc_path.mkdir(parents=True, exist_ok=True)
            pc_uuid = _ensure_local_marker(pc_path, "PC")
            cfg = cls(
                libraries=[Library(name="PC", path=str(pc_path), uuid=pc_uuid)],
            )
            cfg.save()
            return cfg
        with CONFIG_FILE.open() as f:
            data = yaml.safe_load(f) or {}

        # Detect & migrate legacy schemas
        # v1 → v2: introduce libraries (defaults.output_root → libraries[])
        # v2 → v3: drop config.playlists[] (move them to per-library manifests on disk)
        # v3+:    every library should also carry a .mixtape marker (uuid)
        needed_migration = False
        if "libraries" not in data:
            data = _migrate_v1_to_v2(data)
            needed_migration = True
        if data.get("playlists"):  # v2 → v3
            _snapshot_playlists_to_disk(data)
            data.pop("playlists", None)
            needed_migration = True

        defaults = Defaults(**(data.get("defaults") or {}))
        libraries = [Library(**lib) for lib in (data.get("libraries") or [])]
        # Backfill missing UUIDs by writing a .mixtape marker into each
        # online library — same identity model for PC and USB.
        for lib in libraries:
            if not lib.uuid and lib.online:
                lib.uuid = _ensure_local_marker(lib.root, lib.name)
                needed_migration = True
        active = data.get("active_library") or (libraries[0].name if libraries else "PC")
        close_to_tray = bool(data.get("close_to_tray", False))
        cfg = cls(
            defaults=defaults, active_library=active, libraries=libraries,
            close_to_tray=close_to_tray,
        )
        if needed_migration:
            cfg.save()
        return cfg

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w") as f:
            yaml.safe_dump(
                {
                    "defaults": asdict(self.defaults),
                    "active_library": self.active_library,
                    "close_to_tray": self.close_to_tray,
                    "libraries": [asdict(lib) for lib in self.libraries],
                },
                f, sort_keys=False, allow_unicode=True,
            )

    # --- library helpers ---

    def active_library_obj(self) -> Library:
        for lib in self.libraries:
            if lib.name == self.active_library:
                return lib
        if self.libraries:
            return self.libraries[0]
        return Library(name="PC", path=str(Path.home() / "Music/mixtape"))

    def set_active_library(self, name: str) -> None:
        if any(lib.name == name for lib in self.libraries):
            self.active_library = name
            self.save()

    def add_library(self, library: Library) -> None:
        if any(lib.name == library.name for lib in self.libraries):
            raise ValueError(f"library named {library.name!r} already exists")
        self.libraries.append(library)
        self.save()

    def remove_library(self, name: str) -> None:
        if name == self.active_library and len(self.libraries) > 1:
            self.active_library = next(
                (lib.name for lib in self.libraries if lib.name != name), name,
            )
        self.libraries = [lib for lib in self.libraries if lib.name != name]
        self.save()

    def get_library(self, name: str) -> Library | None:
        return next((lib for lib in self.libraries if lib.name == name), None)

    def get_library_by_uuid(self, uid: str) -> Library | None:
        if not uid:
            return None
        return next((lib for lib in self.libraries if lib.uuid == uid), None)

    # --- playlists (read-through to disk) ---

    def playlists_for(self, library: Library) -> list[Playlist]:
        """Discover playlists from the library's on-disk manifests. Source of
        truth — no caching here so changes show up immediately."""
        if not library.online:
            return []
        # Local import to avoid the config <-> manifest <-> downloader cycle
        from .manifest import Manifest
        out: list[Playlist] = []
        for sub in sorted(p for p in library.root.iterdir() if p.is_dir()):
            mp = sub / ".manifest.yaml"
            if not mp.is_file():
                continue
            m = Manifest.load(mp)
            if not m.url:
                continue
            out.append(Playlist(
                name=m.name or sub.name,
                url=m.url,
                format=m.format or self.defaults.format,
                quality=m.quality or self.defaults.quality,
                relative_path=sub.name,
                last_sync=m.last_sync or None,
                track_count=len(m.tracks),
                requires_cookies=m.requires_cookies,
            ))
        return out

    def active_playlists(self) -> list[Playlist]:
        return self.playlists_for(self.active_library_obj())

    # --- playlist mutations (write to disk) ---

    def add_playlist(self, p: Playlist) -> None:
        """Create a playlist on the active library (writes its .manifest.yaml)."""
        self._write_playlist(self.active_library_obj(), p)

    def update_playlist(self, p: Playlist) -> None:
        """Update by relative_path (the on-disk identity)."""
        self._write_playlist(self.active_library_obj(), p)

    def remove_playlist(self, p: Playlist, *, also_files: bool = False) -> None:
        import shutil
        lib = self.active_library_obj()
        d = p.expanded_dir_for(lib)
        if not d.is_dir():
            return
        if also_files:
            shutil.rmtree(d, ignore_errors=True)
        else:
            # Just remove the playlist's identity, keep audio files alone
            for fname in (".manifest.yaml", ".archive"):
                (d / fname).unlink(missing_ok=True)

    def mark_synced(self, p: Playlist, track_count: int) -> None:
        """Update the playlist's last_sync + track_count on disk."""
        lib = self.active_library_obj()
        from .manifest import Manifest
        mp = p.expanded_dir_for(lib) / ".manifest.yaml"
        m = Manifest.load(mp) if mp.exists() else Manifest()
        m.url = p.url; m.name = p.name
        m.format = p.format; m.quality = p.quality
        m.requires_cookies = p.requires_cookies
        m.last_sync = datetime.now().isoformat(timespec="seconds")
        m.save(mp)

    def _write_playlist(self, library: Library, p: Playlist) -> None:
        from .manifest import Manifest
        if not library.online:
            raise RuntimeError(
                f"Library {library.name!r} is offline ({library.path}) — "
                "plug the device or switch active library before adding/editing."
            )
        d = p.expanded_dir_for(library)
        d.mkdir(parents=True, exist_ok=True)
        mp = d / ".manifest.yaml"
        m = Manifest.load(mp) if mp.exists() else Manifest()
        m.url = p.url
        m.name = p.name
        m.format = p.format
        m.quality = p.quality
        m.requires_cookies = p.requires_cookies
        m.save(mp)


# ── migrations ──────────────────────────────────────────────────────────────

def _filter_known_fields(d: dict, cls) -> dict:
    known = {f.name for f in cls.__dataclass_fields__.values()}
    return {k: v for k, v in d.items() if k in known}


def _migrate_v1_to_v2(data: dict) -> dict:
    """v1: defaults.output_root + playlists[].output_dir.
    v2: libraries[] + playlists[].relative_path."""
    defaults = data.get("defaults") or {}
    output_root = defaults.get("output_root") or str(Path.home() / "Music/mixtape")
    abs_root = Path(output_root).expanduser()
    libraries = [{"name": "PC", "path": str(abs_root), "volume_name": "", "auto_sync": False}]
    new_playlists = []
    for p in data.get("playlists") or []:
        np = dict(p)
        old_dir = np.pop("output_dir", None)
        if old_dir and not np.get("relative_path"):
            try:
                rel = Path(old_dir).expanduser().relative_to(abs_root)
                np["relative_path"] = str(rel)
            except ValueError:
                pass
        new_playlists.append(np)
    return {
        "defaults": {"format": defaults.get("format", "mp3"), "quality": defaults.get("quality", "0")},
        "active_library": "PC",
        "libraries": libraries,
        "playlists": new_playlists,
    }


def _snapshot_playlists_to_disk(data: dict) -> None:
    """v2 → v3: persist each config-level playlist into the active library's
    on-disk manifest, then drop ``playlists:`` from the config. Idempotent —
    if a manifest already has a URL, we don't overwrite it."""
    from .manifest import Manifest
    libs = data.get("libraries") or []
    active_name = data.get("active_library") or (libs[0]["name"] if libs else "PC")
    active = next((lib for lib in libs if lib["name"] == active_name), libs[0] if libs else None)
    if not active:
        return
    root = Path(active["path"]).expanduser()
    if not root.is_dir():
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return  # active library offline at migration time — best effort
    for p in data.get("playlists") or []:
        rel = p.get("relative_path") or _slugify(p.get("name", "playlist"))
        d = root / rel
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        mp = d / ".manifest.yaml"
        m = Manifest.load(mp) if mp.exists() else Manifest()
        if m.url:  # already has identity from a previous sync — leave it
            continue
        m.url = p.get("url", "")
        m.name = p.get("name", "")
        m.format = p.get("format", "mp3")
        m.quality = p.get("quality", "0")
        m.requires_cookies = bool(p.get("requires_cookies", True))
        m.last_sync = p.get("last_sync") or None
        try:
            m.save(mp)
        except OSError:
            continue


def ensure_local_marker(root: Path, name: str) -> str:
    """Public alias for the historical ``_ensure_local_marker``."""
    return _ensure_local_marker(root, name)


def _ensure_local_marker(root: Path, name: str) -> str:
    """Write a .mixtape marker at ``root`` if absent and return its UUID.
    Used to give every library — PC included — a stable cross-machine identity."""
    from .library_marker import LibraryMarker, read_marker, write_marker
    existing = read_marker(root)
    if existing:
        return existing.uuid
    marker = LibraryMarker.new(name=name, auto_sync=False, mixtape_version="0.1.0b1")
    try:
        write_marker(root, marker)
    except OSError:
        pass
    return marker.uuid


def cookies_path() -> Path | None:
    return COOKIES_FILE if COOKIES_FILE.exists() else None


def validate_cookies_text(content: str) -> str:
    """Raise ``ValueError`` if ``content`` doesn't look like a YouTube
    Netscape ``cookies.txt``; return it normalised (trailing newline).

    Single source of truth for the heuristic, used by the daemon's
    /cookies endpoint and ``mixtape --set-cookies``."""
    if not content.strip():
        raise ValueError("empty cookies content")
    if "youtube" not in content.lower() and not content.lstrip().startswith("# Netscape"):
        raise ValueError("doesn't look like a YouTube cookies.txt — refusing")
    return content if content.endswith("\n") else content + "\n"


def write_cookies(content: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_FILE.write_text(content)
    COOKIES_FILE.chmod(0o600)
