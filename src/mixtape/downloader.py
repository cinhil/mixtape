from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import sanitize_filename

from .config import Library, Playlist, cookies_path
from .manifest import Manifest, Track, expected_prefix, migrate_filenames


def _verbose_enabled() -> bool:
    return os.environ.get("YTMUSIC_TUI_VERBOSE", "").strip() not in ("", "0", "false", "no")


class CancelledError(Exception):
    """Raised inside yt-dlp hooks when the user cancels."""


class _TUILogger:
    """Capture yt-dlp log output and forward errors/warnings to the UI.

    When verbose=True, also forwards [info] lines (e.g. "Downloading X player API
    JSON") so we can see which yt-dlp clients are tried and where they fail.
    """

    def __init__(
        self,
        on_event: "ProgressCallback",
        playlist_idx: int,
        verbose: bool = False,
    ) -> None:
        self.on_event = on_event
        self.playlist_idx = playlist_idx
        self.verbose = verbose
        self.error_count = 0
        self.last_error: str = ""

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        if self.verbose:
            self._send(f"[dim]· {msg}[/dim]")

    def info(self, msg: str) -> None:
        if self.verbose:
            self._send(f"[dim]· {msg}[/dim]")

    def warning(self, msg: str) -> None:
        self._send(f"⚠ {msg}")

    def error(self, msg: str) -> None:
        self.error_count += 1
        clean = re.sub(r"\x1b\[[0-9;]*m", "", msg)
        clean = re.sub(r"^\s*ERROR:\s*", "", clean).strip()
        if not clean:
            clean = "(empty error from yt-dlp — likely a format/auth failure earlier in the log)"
        self.last_error = clean
        self._send(f"[red]ERROR[/red] {clean}")

    def _send(self, msg: str) -> None:
        self.on_event(ProgressEvent(kind="log", playlist_idx=self.playlist_idx, message=msg))


@dataclass
class PlaylistMeta:
    title: str
    url: str
    count: int


def _base_opts(cookies: Path | None = None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "extract_flat": False,
        # Auto-fetch the EJS challenge solver from yt-dlp's github so the JS
        # signature/n-challenge can be solved via Deno. Required since 2024.
        "remote_components": ["ejs:github"],
        "extractor_args": {
            # Client priority list — yt-dlp queries each and merges the
            # available audio formats; bestaudio/best then picks the highest
            # bitrate among them. tv_simply is omitted because it doesn't
            # support session cookies (would just be skipped with a warning).
            "youtube": {"player_client": ["tv", "web", "web_music"]},
        },
    }
    # No extractor_args needed for bgutil:http — the Python plugin auto-discovers
    # the daemon at 127.0.0.1:4416 (started by app.py on_mount). When the daemon
    # isn't running, yt-dlp falls back to the tv client (Opus ~135k) cleanly.
    if cookies and cookies.exists():
        opts["cookiefile"] = str(cookies)
    return opts


def fetch_playlist_meta(url: str) -> PlaylistMeta:
    """Fetch playlist title and entry count without downloading."""
    opts = _base_opts(cookies_path())
    opts.update({"extract_flat": "in_playlist", "skip_download": True})
    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=False) or {}
    title = info.get("title") or info.get("playlist_title") or "(untitled)"
    entries = info.get("entries") or []
    return PlaylistMeta(title=title, url=url, count=len(entries))


def list_user_library() -> list[PlaylistMeta]:
    """List user's YouTube playlists. Requires cookies (logged-in session)."""
    cookies = cookies_path()
    if not cookies:
        raise RuntimeError("No cookies configured — paste cookies first.")
    opts = _base_opts(cookies)
    opts.update({"extract_flat": "in_playlist", "skip_download": True})
    results: list[PlaylistMeta] = []
    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info("https://www.youtube.com/feed/playlists", download=False) or {}
        for entry in info.get("entries") or []:
            if not entry:
                continue
            url = entry.get("url") or entry.get("webpage_url")
            title = entry.get("title") or "(untitled)"
            count = entry.get("playlist_count") or 0
            if url:
                results.append(PlaylistMeta(title=title, url=url, count=count))
    return results


@dataclass
class ProgressEvent:
    """Sent to UI during downloads."""

    kind: str  # 'start', 'progress', 'finished', 'log', 'done', 'error', 'cancelled', 'source'
    playlist_idx: int = 0
    track_idx: int = 0  # 1-based position in current playlist sync
    track_total: int = 0
    track_number: int = 0  # stable manifest-assigned number (used as filename prefix)
    track_title: str = ""
    percent: float = 0.0
    message: str = ""
    source: str = ""  # short source label e.g. "AAC 256k (copy)"


ProgressCallback = Callable[[ProgressEvent], None]


def _format_selector(target: str) -> str:
    """Prefer a source codec matching the target so ffmpeg can copy without re-encoding."""
    target = target.lower()
    if target == "m4a":
        return "bestaudio[ext=m4a]/bestaudio"
    if target == "opus":
        return "bestaudio[ext=webm][acodec=opus]/bestaudio[acodec=opus]/bestaudio"
    if target == "flac":
        return "bestaudio[acodec=flac]/bestaudio"
    # mp3 always re-encodes (no MP3 source on YouTube)
    return "bestaudio/best"


def _normalize_codec(acodec: str) -> str:
    c = (acodec or "").lower()
    if c.startswith("mp4a"):
        return "AAC"
    if c == "opus":
        return "Opus"
    if c == "flac":
        return "FLAC"
    if c == "mp3":
        return "MP3"
    if c == "vorbis":
        return "Vorbis"
    return acodec.upper() if acodec else "?"


def _resolve_channel_name(channel_id: str, ydl: "yt_dlp.YoutubeDL") -> str | None:
    """Quick lookup of a YouTube channel's display name by its UC… id.
    Used when the per-track player API returns no artist/uploader (typical for
    some YouTube Music 'song' entries — only channel_id is set)."""
    try:
        info = ydl.extract_info(
            f"https://www.youtube.com/channel/{channel_id}",
            download=False, process=False,
        ) or {}
    except Exception:  # noqa: BLE001
        return None
    return info.get("channel") or info.get("uploader") or None


def _will_copy(source_codec: str, source_ext: str, target_format: str) -> bool:
    """Whether ffmpeg will stream-copy (no re-encode) when source matches target."""
    target = target_format.lower()
    sc = (source_codec or "").lower()
    se = (source_ext or "").lower()
    if target == "m4a":
        return sc.startswith("mp4a") or se == "m4a"
    if target == "opus":
        return sc == "opus"
    if target == "flac":
        return sc == "flac"
    if target == "mp3":
        return sc == "mp3"  # never on YouTube
    return False


def sync_playlist(
    playlist: Playlist,
    library: Library,
    playlist_idx: int,
    on_event: ProgressCallback,
    cancel: threading.Event | None = None,
) -> int:
    """Download missing tracks into ``library``. Returns total tracks in playlist.

    Numbering is stable per video_id via a manifest stored in the output dir.
    Pass `cancel` to allow user-driven interruption between tracks (and inside
    the current download via the progress hook).
    """
    out_dir = playlist.expanded_dir_for(library)
    archive_file = playlist.archive_file_for(library)
    out_dir.mkdir(parents=True, exist_ok=True)

    cancel = cancel or threading.Event()

    # --- Pre-flight: list entries (flat, fast) ---
    flat_opts = {**_base_opts(cookies_path()), "extract_flat": "in_playlist", "skip_download": True}
    with yt_dlp.YoutubeDL(flat_opts) as ydl:  # type: ignore[arg-type]
        flat = ydl.extract_info(playlist.url, download=False) or {}
    entries = [e for e in (flat.get("entries") or []) if e]

    # --- Manifest: stable per-video numbering ---
    manifest_path = out_dir / ".manifest.yaml"
    manifest = Manifest.load(manifest_path)

    # Detect format/quality change → force re-encode of existing tracks
    fmt = playlist.format.lower()
    quality = playlist.quality or "0"
    settings_changed = bool(manifest.format) and (
        manifest.format != fmt or manifest.quality != quality
    )
    if settings_changed:
        on_event(
            ProgressEvent(
                kind="log",
                playlist_idx=playlist_idx,
                message=(
                    f"Settings changed ({manifest.format}/{manifest.quality} → {fmt}/{quality}) "
                    f"— wiping archive and old files, re-encoding all tracks."
                ),
            )
        )
        # Delete old audio files referenced by the manifest
        for track in manifest.tracks.values():
            if track.filename:
                old = out_dir / track.filename
                if old.exists():
                    try:
                        old.unlink()
                    except OSError:
                        pass
                track.filename = ""
        # Wipe the archive so yt-dlp re-downloads everything
        if archive_file.exists():
            try:
                archive_file.unlink()
            except OSError:
                pass

    # Re-derive numbers from the *current* YouTube order so reorderings on the
    # playlist propagate to local file numbering. Existing files are renamed by
    # migrate_filenames below. Tracks no longer in YT keep their old number
    # (their file becomes an orphan with that old prefix on disk).
    renumbered = 0
    for i, entry in enumerate(entries, start=1):
        vid = entry.get("id")
        if not vid:
            continue
        title = entry.get("title") or ""
        if vid in manifest.tracks:
            t = manifest.tracks[vid]
            if t.number != i:
                renumbered += 1
            t.number = i
            if title and not t.title:
                t.title = title
        else:
            manifest.tracks[vid] = Track(number=i, title=title)
    if renumbered:
        on_event(
            ProgressEvent(
                kind="log",
                playlist_idx=playlist_idx,
                message=f"Playlist reordered on YouTube — {renumbered} track(s) will be renumbered/renamed.",
            )
        )

    manifest.format = fmt
    manifest.quality = quality
    # Snapshot the playlist's identity so any mixtape installation that later
    # plugs in this device can re-discover the playlist from disk alone.
    manifest.url = playlist.url
    manifest.name = playlist.name
    manifest.requires_cookies = playlist.requires_cookies
    manifest.save(manifest_path)
    pad = manifest.padding()

    # Apply renumber/migrate: rename files on disk so the prefix matches the
    # newly-assigned number. Same code path also fixes legacy "NA - …" files.
    renamed = migrate_filenames(out_dir, manifest, pad)
    if renamed:
        for old_name, new_name in renamed:
            on_event(ProgressEvent(kind="log", playlist_idx=playlist_idx, message=f"Renamed: {old_name} → {new_name}"))
        manifest.save(manifest_path)

    on_event(
        ProgressEvent(
            kind="start",
            playlist_idx=playlist_idx,
            track_total=len(entries),
            message=f"{playlist.name}: {len(entries)} tracks",
        )
    )

    is_windows_fs = str(out_dir).startswith("/mnt/")

    state: dict[str, Any] = {
        "track_idx": 0,
        "track_total": len(entries),
        "track_number": 0,
        "current_title": "",
        "current_source": "",
    }
    logged_sources: set[str] = set()

    def _emit_source_info(info: dict[str, Any]) -> None:
        vid = info.get("id")
        if not vid or vid in logged_sources:
            return
        logged_sources.add(vid)
        codec = _normalize_codec(info.get("acodec", ""))
        ext = info.get("ext", "?")
        abr = info.get("abr") or info.get("tbr")
        format_id = info.get("format_id", "?")
        bitrate = f"{abr:.0f}k" if abr else "?"
        copy = _will_copy(info.get("acodec", ""), ext, fmt)
        action = "[green]copy[/green]" if copy else f"[yellow]re-encode → {fmt}[/yellow]"
        short = f"{codec} {bitrate} ({'copy' if copy else 're-enc'})"
        state["current_source"] = short
        title = info.get("title") or state["current_title"]
        on_event(
            ProgressEvent(
                kind="source",
                playlist_idx=playlist_idx,
                track_idx=state["track_idx"],
                track_total=state["track_total"],
                track_number=state["track_number"],
                track_title=title,
                source=short,
                message=f"Source: {codec} {bitrate} ({ext}, itag {format_id}) — {action}",
            )
        )

    def progress_hook(d: dict[str, Any]) -> None:
        if cancel.is_set():
            raise CancelledError()
        status = d.get("status")
        info = d.get("info_dict") or {}
        title = info.get("title") or ""
        if status == "downloading":
            _emit_source_info(info)
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100.0) if total else 0.0
            on_event(
                ProgressEvent(
                    kind="progress",
                    playlist_idx=playlist_idx,
                    track_idx=state["track_idx"],
                    track_total=state["track_total"],
                    track_number=state["track_number"],
                    track_title=title or state["current_title"],
                    percent=pct,
                    source=state["current_source"],
                )
            )
        elif status == "finished":
            _emit_source_info(info)
            on_event(
                ProgressEvent(
                    kind="finished",
                    playlist_idx=playlist_idx,
                    track_idx=state["track_idx"],
                    track_total=state["track_total"],
                    track_number=state["track_number"],
                    track_title=title or state["current_title"],
                    percent=100.0,
                    source=state["current_source"],
                )
            )

    def postprocessor_hook(d: dict[str, Any]) -> None:
        # Capture the final on-disk filename after thumbnail embed (last PP step).
        if d.get("status") == "finished" and d.get("postprocessor") == "EmbedThumbnail":
            info = d.get("info_dict") or {}
            vid = info.get("id")
            filepath = info.get("filepath")
            if vid and filepath and vid in manifest.tracks:
                manifest.tracks[vid].filename = Path(filepath).name

    logger = _TUILogger(on_event, playlist_idx, verbose=_verbose_enabled())
    cancelled = False
    success_count = 0
    failures: list[tuple[int, str, str, str]] = []  # (number, title, video_id, reason)
    channel_name_cache: dict[str, str] = {}  # channel_id -> resolved name (per-sync)

    # Read the download_archive ourselves so we can skip already-fetched tracks
    # *before* the probe call. Without this, every sync re-probes every entry
    # even when nothing needs downloading (~3-5s per probe × N tracks).
    archive_ids: set[str] = set()
    if archive_file.exists():
        try:
            for line in archive_file.read_text().splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == "youtube":
                    archive_ids.add(parts[1])
        except OSError:
            pass
    try:
        for i, entry in enumerate(entries, start=1):
            if cancel.is_set():
                cancelled = True
                break
            vid = entry.get("id")
            if not vid:
                continue
            num = manifest.tracks[vid].number
            state["track_idx"] = i
            state["track_number"] = num
            state["current_title"] = entry.get("title") or ""

            outtmpl = str(out_dir / f"{expected_prefix(num, pad)}%(artist,uploader)s - %(title)s.%(ext)s")
            opts: dict[str, Any] = {
                **_base_opts(cookies_path()),
                "format": _format_selector(fmt),
                "outtmpl": outtmpl,
                "download_archive": str(archive_file),
                "ignoreerrors": True,
                "writethumbnail": True,
                "windowsfilenames": is_windows_fs,
                "logger": logger,
                "progress_hooks": [progress_hook],
                "postprocessor_hooks": [postprocessor_hook],
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": fmt, "preferredquality": quality},
                    {"key": "FFmpegMetadata", "add_metadata": True},
                    {"key": "EmbedThumbnail", "already_have_thumbnail": False},
                ],
                "noprogress": True,
                "consoletitle": False,
            }
            video_url = entry.get("url") or entry.get("webpage_url")
            if not video_url:
                continue

            # Fast path: already in archive, skip probe + download entirely.
            if vid in archive_ids:
                # Tick the progress bar so the UI doesn't look frozen during a
                # long run of already-downloaded tracks.
                on_event(
                    ProgressEvent(
                        kind="progress",
                        playlist_idx=playlist_idx,
                        track_idx=i,
                        track_total=len(entries),
                        track_title=state["current_title"],
                        percent=100.0,
                    )
                )
                continue

            # Probe-only pass to detect tracks where YouTube returns no artist
            # info (some YT Music "song" entries only set channel_id). When we
            # detect that, look up the channel once and rewrite the outtmpl for
            # this single track so the file gets a proper "<Artist> - <Title>"
            # name instead of "NA - <Title>".
            probe_opts = {**_base_opts(cookies_path()), "skip_download": True}
            try:
                with yt_dlp.YoutubeDL(probe_opts) as probe:  # type: ignore[arg-type]
                    info_probe = probe.extract_info(video_url, download=False, process=False) or {}
                if not (info_probe.get("artist") or info_probe.get("uploader") or info_probe.get("channel")):
                    cid = info_probe.get("channel_id")
                    if cid:
                        if cid not in channel_name_cache:
                            with yt_dlp.YoutubeDL(probe_opts) as probe:  # type: ignore[arg-type]
                                resolved = _resolve_channel_name(cid, probe) or ""
                            channel_name_cache[cid] = resolved
                        artist = channel_name_cache.get(cid) or ""
                        if artist:
                            artist_safe = sanitize_filename(artist, restricted=False)
                            opts["outtmpl"] = str(
                                out_dir / f"{expected_prefix(num, pad)}{artist_safe} - %(title)s.%(ext)s"
                            )
            except Exception:  # noqa: BLE001
                pass  # probe failed — continue with default outtmpl

            errors_before = logger.error_count
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
                    ydl.download([video_url])
                if logger.error_count == errors_before:
                    success_count += 1
                else:
                    failures.append((num, state["current_title"], vid, logger.last_error or "unknown error"))
            except CancelledError:
                cancelled = True
                break
            except Exception as e:  # noqa: BLE001
                failures.append((num, state["current_title"], vid, str(e)))
                on_event(
                    ProgressEvent(
                        kind="log",
                        playlist_idx=playlist_idx,
                        message=f"Skip ({state['current_title']}): {e}",
                    )
                )
    finally:
        manifest.save(manifest_path)

    if cancelled:
        on_event(
            ProgressEvent(
                kind="cancelled",
                playlist_idx=playlist_idx,
                track_total=len(entries),
                message=f"{playlist.name}: cancelled at track {state['track_idx']}",
            )
        )
    else:
        if failures:
            on_event(
                ProgressEvent(
                    kind="log",
                    playlist_idx=playlist_idx,
                    message=(
                        f"[red]✗ {len(failures)} track(s) failed[/red] "
                        f"[dim](open the link to fix in your YT Music playlist):[/dim]"
                    ),
                )
            )
            for fnum, ftitle, fvid, freason in failures:
                short_reason = freason.split("\n")[0][:200]
                yt_music_url = f"https://music.youtube.com/watch?v={fvid}"
                on_event(
                    ProgressEvent(
                        kind="log",
                        playlist_idx=playlist_idx,
                        message=(
                            f"   • {expected_prefix(fnum, pad)}{ftitle}  "
                            f"[link={yt_music_url}][cyan]{yt_music_url}[/cyan][/link]  "
                            f"[dim]→ {short_reason}[/dim]"
                        ),
                    )
                )
        summary = f"{success_count}/{len(entries)} downloaded"
        if failures:
            summary += f", {len(failures)} failed"
        on_event(
            ProgressEvent(
                kind="done",
                playlist_idx=playlist_idx,
                track_total=len(entries),
                message=f"{playlist.name}: {summary}",
            )
        )
    return len(entries)
