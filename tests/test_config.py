"""Tests for the config module — slugify, library/playlist helpers, v1→v2 migration."""
from __future__ import annotations

import pytest

from mixtape.config import (
    Config, Defaults, Library, Playlist, _migrate_v1_to_v2, _slugify,
)


# ── _slugify ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Camille playlist 8ans🤩🥳", "Camille playlist 8ans"),
    ("Rock & Roll", "Rock Roll"),
    ("Hits — Top 50", "Hits Top 50"),
    ("   ", "playlist"),       # empty → fallback
    ("", "playlist"),
    ("a/b\\c:d|e?f", "abcdef"),
    ("multi   space  word", "multi space word"),
    ("under_score-dash", "under score dash"),
])
def test_slugify(raw, expected):
    assert _slugify(raw) == expected


# ── Playlist path resolution ────────────────────────────────────────────────

def test_playlist_path_uses_active_library(tmp_path):
    lib = Library(name="X", path=str(tmp_path))
    pl = Playlist(name="Some Playlist", url="https://x", relative_path="custom-folder")
    assert pl.expanded_dir_for(lib) == tmp_path / "custom-folder"
    assert pl.archive_file_for(lib) == tmp_path / "custom-folder" / ".archive"


def test_playlist_relative_path_defaults_to_slug(tmp_path):
    lib = Library(name="X", path=str(tmp_path))
    pl = Playlist(name="My Playlist!!!", url="https://x")  # no relative_path
    assert pl.expanded_dir_for(lib) == tmp_path / "My Playlist"


def test_playlist_requires_cookies_default():
    pl = Playlist(name="X", url="https://x")
    assert pl.requires_cookies is True  # safety default


# ── Library lookups ─────────────────────────────────────────────────────────

def test_library_lookup_by_uuid_and_name():
    cfg = Config(
        defaults=Defaults(),
        libraries=[
            Library(name="PC",  path="/p", uuid="aaa-111"),
            Library(name="USB", path="/u", uuid="bbb-222"),
        ],
        active_library="PC",
    )
    assert cfg.get_library("PC").uuid == "aaa-111"          # type: ignore[union-attr]
    assert cfg.get_library_by_uuid("bbb-222").name == "USB"  # type: ignore[union-attr]
    assert cfg.get_library("nope") is None
    assert cfg.get_library_by_uuid("missing") is None
    assert cfg.get_library_by_uuid("") is None


def test_active_library_obj_falls_back():
    cfg = Config(libraries=[Library(name="A", path="/a")], active_library="bogus")
    assert cfg.active_library_obj().name == "A"  # falls back to first


# ── v1 → v2 migration ───────────────────────────────────────────────────────

def test_migration_creates_pc_library_from_old_output_root():
    v1 = {
        "defaults": {"output_root": "/mnt/c/Music", "format": "m4a", "quality": "192"},
        "playlists": [
            {"name": "P1", "url": "https://x", "output_dir": "/mnt/c/Music/P1",
             "format": "m4a", "quality": "192"},
            {"name": "P2", "url": "https://y", "output_dir": "/mnt/c/Music/sub/P2"},
        ],
    }
    v2 = _migrate_v1_to_v2(v1)
    assert v2["active_library"] == "PC"
    assert v2["libraries"][0]["name"] == "PC"
    assert v2["libraries"][0]["path"] == "/mnt/c/Music"
    assert v2["playlists"][0]["relative_path"] == "P1"
    assert v2["playlists"][1]["relative_path"] == "sub/P2"
    assert "output_dir" not in v2["playlists"][0]


def test_migration_handles_missing_output_dir():
    v1 = {"defaults": {}, "playlists": [{"name": "p", "url": "https://x"}]}
    v2 = _migrate_v1_to_v2(v1)
    assert v2["playlists"][0].get("relative_path", "") == ""
    assert "libraries" in v2 and len(v2["libraries"]) == 1


# ── Config save/load round-trip via env override ─────────────────────────────

def test_config_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    # Re-import config module so the env var is seen by its module-level paths
    import importlib
    import mixtape.config as cfg_mod
    importlib.reload(cfg_mod)
    cfg = cfg_mod.Config(
        defaults=cfg_mod.Defaults(format="opus", quality="192"),
        libraries=[cfg_mod.Library(name="L", path="/some/dir", uuid="abc")],
        active_library="L",
        playlists=[cfg_mod.Playlist(name="P", url="https://x", requires_cookies=False)],
    )
    cfg.save()
    cfg2 = cfg_mod.Config.load()
    assert cfg2.active_library == "L"
    assert cfg2.libraries[0].uuid == "abc"
    assert cfg2.playlists[0].requires_cookies is False
    assert cfg2.defaults.format == "opus"
