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
    """
    name: str
    path: str  # absolute path to the library root
    volume_name: str = ""  # Windows volume label, used for USB auto-detect
    auto_sync: bool = False  # trigger sync automatically on USB plug-in


@dataclass
class Playlist:
    name: str
    url: str
    format: str = "mp3"
    quality: str = "0"
    relative_path: str = ""  # subdir under library root; defaults to slug(name)
    last_sync: str | None = None
    track_count: int = 0

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
    defaults: Defaults = field(default_factory=Defaults)
    active_library: str = "PC"
    libraries: list[Library] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_FILE.exists():
            cfg = cls(
                libraries=[Library(name="PC", path=str(Path.home() / "Music/YTMusic"))],
            )
            cfg.save()
            return cfg
        with CONFIG_FILE.open() as f:
            data = yaml.safe_load(f) or {}

        # Detect & migrate legacy schema (v1 → v2: introduce libraries)
        if "libraries" not in data:
            data = _migrate_v1_to_v2(data)

        defaults = Defaults(**(data.get("defaults") or {}))
        libraries = [Library(**lib) for lib in (data.get("libraries") or [])]
        playlists = [Playlist(**_filter_known_fields(p, Playlist)) for p in (data.get("playlists") or [])]
        active = data.get("active_library") or (libraries[0].name if libraries else "PC")
        cfg = cls(defaults=defaults, active_library=active, libraries=libraries, playlists=playlists)
        # Persist the migrated form so we don't run migration every load
        if "libraries" not in (yaml.safe_load(CONFIG_FILE.read_text()) or {}):
            cfg.save()
        return cfg

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w") as f:
            yaml.safe_dump(
                {
                    "defaults": asdict(self.defaults),
                    "active_library": self.active_library,
                    "libraries": [asdict(lib) for lib in self.libraries],
                    "playlists": [asdict(p) for p in self.playlists],
                },
                f, sort_keys=False, allow_unicode=True,
            )

    # --- library helpers ---

    def active_library_obj(self) -> Library:
        for lib in self.libraries:
            if lib.name == self.active_library:
                return lib
        # Fallback: first library or a synthesized default
        if self.libraries:
            return self.libraries[0]
        return Library(name="PC", path=str(Path.home() / "Music/YTMusic"))

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
            # switch active to the first remaining one
            self.active_library = next((lib.name for lib in self.libraries if lib.name != name), name)
        self.libraries = [lib for lib in self.libraries if lib.name != name]
        self.save()

    def get_library(self, name: str) -> Library | None:
        return next((lib for lib in self.libraries if lib.name == name), None)

    # --- playlist helpers ---

    def add_playlist(self, p: Playlist) -> None:
        self.playlists.append(p)
        self.save()

    def remove_playlist(self, index: int) -> None:
        del self.playlists[index]
        self.save()

    def update_playlist(self, index: int, p: Playlist) -> None:
        self.playlists[index] = p
        self.save()

    def mark_synced(self, index: int, track_count: int) -> None:
        self.playlists[index].last_sync = datetime.now().isoformat(timespec="seconds")
        self.playlists[index].track_count = track_count
        self.save()


def _filter_known_fields(d: dict, cls) -> dict:
    """Drop keys not present on the dataclass — for forward/backward compat."""
    known = {f.name for f in cls.__dataclass_fields__.values()}
    return {k: v for k, v in d.items() if k in known}


def _migrate_v1_to_v2(data: dict) -> dict:
    """v1: defaults.output_root + playlists[].output_dir.
    v2: libraries[] + playlists[].relative_path.
    """
    defaults = data.get("defaults") or {}
    output_root = defaults.get("output_root") or str(Path.home() / "Music/YTMusic")
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
                # output_dir was outside the root — use slug(name) as fallback
                pass
        new_playlists.append(np)

    return {
        "defaults": {"format": defaults.get("format", "mp3"), "quality": defaults.get("quality", "0")},
        "active_library": "PC",
        "libraries": libraries,
        "playlists": new_playlists,
    }


def cookies_path() -> Path | None:
    return COOKIES_FILE if COOKIES_FILE.exists() else None


def write_cookies(content: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_FILE.write_text(content)
    COOKIES_FILE.chmod(0o600)
