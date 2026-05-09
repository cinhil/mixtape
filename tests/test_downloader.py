"""Pure-logic tests for the download module — no network."""
from __future__ import annotations

import pytest

from mixtape.downloader import _format_selector, _normalize_codec, _will_copy


@pytest.mark.parametrize("target,expected_substring", [
    ("mp3",  "bestaudio/best"),
    ("m4a",  "[ext=m4a]"),
    ("opus", "[acodec=opus]"),
    ("flac", "[acodec=flac]"),
])
def test_format_selector_prefers_matching_codec(target, expected_substring):
    sel = _format_selector(target)
    assert expected_substring in sel
    # Always falls back to bestaudio
    assert "bestaudio" in sel


@pytest.mark.parametrize("acodec,expected", [
    ("mp4a.40.2", "AAC"),
    ("mp4a.40.5", "AAC"),
    ("opus",       "Opus"),
    ("flac",       "FLAC"),
    ("mp3",        "MP3"),
    ("vorbis",     "Vorbis"),
    ("",           "?"),
    ("weird-codec", "WEIRD-CODEC"),
])
def test_normalize_codec(acodec, expected):
    assert _normalize_codec(acodec) == expected


@pytest.mark.parametrize("source_codec,source_ext,target,expected", [
    ("mp4a.40.2", "m4a",  "m4a",  True),    # AAC source, m4a target → copy
    ("opus",       "webm", "m4a",  False),   # Opus → m4a → must transcode
    ("opus",       "webm", "opus", True),    # Opus → opus → copy
    ("flac",       "flac", "flac", True),    # FLAC → FLAC → copy
    ("mp4a.40.2", "m4a",  "mp3",  False),   # always re-encode for mp3
    ("",           "",     "m4a",  False),   # missing info → safe default
])
def test_will_copy(source_codec, source_ext, target, expected):
    assert _will_copy(source_codec, source_ext, target) is expected
