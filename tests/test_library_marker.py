"""Tests for the .mixtape library marker + playlist discovery."""
from __future__ import annotations

from mixtape.library_marker import (
    LibraryMarker, MARKER_FILENAME, discover_playlists, find_marker_on_volume,
    read_marker, write_marker,
)
from mixtape.manifest import Manifest, Track


def test_marker_roundtrip(tmp_path):
    m = LibraryMarker.new(name="USB MP3 Player", auto_sync=True, mixtape_version="0.1.0b1")
    write_marker(tmp_path, m)
    assert (tmp_path / MARKER_FILENAME).exists()
    read = read_marker(tmp_path)
    assert read is not None
    assert read.uuid == m.uuid
    assert read.name == "USB MP3 Player"
    assert read.auto_sync is True


def test_read_marker_missing_returns_none(tmp_path):
    assert read_marker(tmp_path) is None


def test_read_marker_malformed(tmp_path):
    (tmp_path / MARKER_FILENAME).write_text("not: valid: yaml: at all: [")
    assert read_marker(tmp_path) is None


def test_find_marker_at_root(tmp_path):
    m = LibraryMarker.new(name="X")
    write_marker(tmp_path, m)
    hit = find_marker_on_volume(tmp_path)
    assert hit is not None
    assert hit[0].uuid == m.uuid
    assert hit[1] == tmp_path


def test_find_marker_in_music_subdir(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    m = LibraryMarker.new(name="USB")
    write_marker(music, m)
    hit = find_marker_on_volume(tmp_path)
    assert hit is not None
    assert hit[1] == music


def test_find_marker_no_match(tmp_path):
    (tmp_path / "music").mkdir()
    assert find_marker_on_volume(tmp_path) is None


def test_discover_playlists_reads_per_subdir_manifests(tmp_path):
    # Library root with 2 playlist subdirs, each with a .manifest.yaml.
    p1 = tmp_path / "Playlist One"
    p2 = tmp_path / "Playlist Two"
    p1.mkdir(); p2.mkdir()
    Manifest(
        url="https://music.youtube.com/playlist?list=AAA",
        name="Playlist One", format="mp3", quality="0",
        requires_cookies=True,
        tracks={"v1": Track(number=1, title="t1", filename="001 - t1.mp3")},
    ).save(p1 / ".manifest.yaml")
    Manifest(
        url="https://music.youtube.com/playlist?list=BBB",
        name="Playlist Two", format="m4a", quality="192",
        requires_cookies=False,
        tracks={},
    ).save(p2 / ".manifest.yaml")

    found = discover_playlists(tmp_path)
    found_by_name = {f["name"]: f for f in found}
    assert set(found_by_name) == {"Playlist One", "Playlist Two"}
    assert found_by_name["Playlist One"]["url"] == "https://music.youtube.com/playlist?list=AAA"
    assert found_by_name["Playlist One"]["track_count"] == 1
    assert found_by_name["Playlist Two"]["requires_cookies"] is False
    assert found_by_name["Playlist Two"]["format"] == "m4a"


def test_discover_skips_subdirs_without_url(tmp_path):
    """Legacy manifests without the playlist-level URL field should be ignored
    (they predate the portable-library feature)."""
    p = tmp_path / "Legacy"
    p.mkdir()
    # url empty → discover skips
    Manifest(format="mp3", quality="0", tracks={}).save(p / ".manifest.yaml")
    assert discover_playlists(tmp_path) == []


def test_discover_returns_empty_for_non_dir(tmp_path):
    assert discover_playlists(tmp_path / "missing") == []


def test_discover_then_import_dedupes_by_url(tmp_path):
    """Mimic what DeviceSetupScreen does: discover playlists on a freshly
    plugged device, then merge them into the central config — without
    duplicating ones the user already knows about."""
    # Build a mini-library on the "device"
    p_known = tmp_path / "Already known"
    p_new = tmp_path / "Brand new"
    p_known.mkdir(); p_new.mkdir()
    Manifest(
        url="https://music.youtube.com/playlist?list=KNOWN",
        name="Already known", format="mp3", quality="0",
        tracks={"v": Track(number=1, title="t", filename="001 - t.mp3")},
    ).save(p_known / ".manifest.yaml")
    Manifest(
        url="https://music.youtube.com/playlist?list=NEW",
        name="Brand new", format="m4a", quality="192",
        requires_cookies=False,
        tracks={},
    ).save(p_new / ".manifest.yaml")

    # User's central config already has the "known" one
    from mixtape.config import Playlist
    central: list[Playlist] = [
        Playlist(name="Already known", url="https://music.youtube.com/playlist?list=KNOWN",
                 format="mp3", quality="0"),
    ]

    # The merge logic the device-setup screen runs
    known_urls = {p.url for p in central}
    imported = 0
    for entry in discover_playlists(tmp_path):
        if entry["url"] in known_urls:
            continue
        central.append(Playlist(
            name=entry["name"], url=entry["url"],
            format=entry["format"], quality=entry["quality"],
            relative_path=entry["relative_path"],
            requires_cookies=entry["requires_cookies"],
        ))
        known_urls.add(entry["url"])
        imported += 1

    assert imported == 1
    assert {p.url for p in central} == {
        "https://music.youtube.com/playlist?list=KNOWN",
        "https://music.youtube.com/playlist?list=NEW",
    }
    new_one = next(p for p in central if p.url.endswith("NEW"))
    assert new_one.requires_cookies is False
    assert new_one.format == "m4a"
