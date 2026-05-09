"""Tests for the manifest module — round-trip, numbering, file rename pass."""
from __future__ import annotations

from pathlib import Path

import pytest

from mixtape.manifest import (
    Manifest, Track, expected_prefix, migrate_filenames,
)


def test_manifest_roundtrip(tmp_path):
    m = Manifest(
        url="https://music.youtube.com/playlist?list=ABC",
        name="My Playlist",
        format="m4a",
        quality="192",
        requires_cookies=False,
        tracks={
            "vid_a": Track(number=1, title="A", filename="001 - A.m4a"),
            "vid_b": Track(number=2, title="B", filename="002 - B.m4a"),
        },
    )
    p = tmp_path / "m.yaml"
    m.save(p)
    m2 = Manifest.load(p)
    assert m2.url == m.url
    assert m2.name == m.name
    assert m2.format == m.format
    assert m2.quality == m.quality
    assert m2.requires_cookies is False
    assert set(m2.tracks) == {"vid_a", "vid_b"}
    assert m2.tracks["vid_a"].number == 1


def test_manifest_load_missing_returns_empty(tmp_path):
    m = Manifest.load(tmp_path / "absent.yaml")
    assert m.tracks == {}
    assert m.requires_cookies is True  # safety default


def test_manifest_assign_is_stable():
    m = Manifest()
    n1 = m.assign("vid1", "title1")
    n2 = m.assign("vid2", "title2")
    n3 = m.assign("vid1", "title1")  # repeat → same number
    assert n1 == 1 and n2 == 2 and n3 == n1


def test_manifest_padding_grows_with_count():
    m = Manifest()
    for i in range(5):
        m.assign(f"v{i}", f"t{i}")
    assert m.padding() == 3
    # Force a higher number
    m.tracks["x"] = Track(number=1500, title="big")
    assert m.padding() == 4


def test_expected_prefix():
    assert expected_prefix(7, 3) == "007 - "
    assert expected_prefix(123, 4) == "0123 - "


# ── migrate_filenames: NA-prefix migration ──────────────────────────────────

def test_migrate_renames_legacy_NA_prefix(tmp_path):
    # Pre-existing file with NA prefix
    f = tmp_path / "NA - Artist - Track.m4a"
    f.write_text("audio")
    m = Manifest(tracks={"vid": Track(number=5, title="Track", filename="")})
    renames = migrate_filenames(tmp_path, m, pad=3)
    assert renames == [(f.name, "005 - Artist - Track.m4a")]
    assert (tmp_path / "005 - Artist - Track.m4a").exists()
    assert m.tracks["vid"].filename == "005 - Artist - Track.m4a"


# ── migrate_filenames: A↔B swap (the tricky case) ──────────────────────────

def test_migrate_swap_two_tracks(tmp_path):
    """When two tracks swap numbers, the two-pass temp rename must avoid collisions."""
    (tmp_path / "001 - Foo - A.m4a").write_text("a")
    (tmp_path / "002 - Bar - B.m4a").write_text("b")
    m = Manifest(tracks={
        "aaa": Track(number=2, title="A", filename="001 - Foo - A.m4a"),
        "bbb": Track(number=1, title="B", filename="002 - Bar - B.m4a"),
    })
    renames = migrate_filenames(tmp_path, m, pad=3)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["001 - Bar - B.m4a", "002 - Foo - A.m4a"]
    assert len(renames) == 2
