# Changelog

All notable changes to mixtape are tracked here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/) modulo the pre-1.0 reservations.

## 0.1.0b2 — 2026-05-09

A foundational rewrite into a **daemon-and-clients architecture**. The
in-process Textual app + pystray tray are gone, replaced by:

  - a long-running **`mixtape-daemon`** Python process that owns sync,
    USB watching, bgutil supervision, cookies, updates;
  - a **thin TUI client** (`mixtape`) that connects over local
    HTTP+WebSocket;
  - an optional **native Qt desktop UI** (`mixtape --desktop`) with
    `QSystemTrayIcon` — single process, one event loop, no IPC dance.

### Added
  - `mixtape-daemon` entry point (and `mixtape --daemon` alias).
  - Local REST + WebSocket API on `127.0.0.1:<ephemeral>` with a
    256-bit bearer token (chmod 600) written to `state/api.json`.
  - macOS support: `_DarwinBackend` enumerating `/Volumes` (with
    `diskutil info -plist` enrichment), LaunchAgent installer
    (`install.sh --launchd`).
  - PySide6 desktop UI behind the `desktop` extra: playlist table,
    per-row sync progress bars, cookie paste, settings dialog, native
    tray.
  - Tests: `tests/test_services.py` + `tests/test_daemon.py` —
    end-to-end daemon boot + REST + WS auth + event stream.

### Changed
  - Linux installer (`install.sh`) now also runs on macOS (`brew`
    + `--launchd`); supports `--desktop` for the optional GUI.
  - Windows installer (`install.ps1`) now installs a Startup-folder
    shortcut launching `pythonw.exe -m mixtape.daemon.main` (no
    console window). `-Desktop` adds the PySide6 GUI.
  - `mixtape.service` runs `mixtape-daemon` instead of
    `mixtape --headless`.
  - All UIs go through `LibraryService` / `CookieService` /
    `SyncService` / etc. — no more in-process Config writes from the
    UI side.

### Removed
  - `pystray` runtime dep + the `tray.py` module + every dual-process
    workaround it spawned (`tray.pid`, `tui.pid`, `spawn_detached`,
    `kill_running_tray`, `DETACHED_PROCESS` ceremony).
  - In-process `MixtapeApp` Textual class + the `screens/` package
    (replaced by `tui/screens/` thin clients).
  - `headless.py` — the daemon replaces it. `mixtape --headless` still
    works as a deprecated alias for `mixtape --daemon`.

### Notes for upgraders
  - The first launch after upgrade will spawn a fresh daemon; existing
    libraries / cookies / playlists are preserved (Config + manifests
    on disk are unchanged).
  - If you had a `systemd --user` unit named `mixtape.service`, re-run
    `install.sh --systemd` to refresh `ExecStart` to `mixtape-daemon`.
  - macOS users: pass `--launchd` to `install.sh` to install a
    LaunchAgent.
  - Windows users: re-running the one-liner installs the new Startup
    shortcut. The old desktop shortcut still launches the TUI.

## 0.1.0b1 — initial public beta

Single-process Textual TUI + pystray tray + headless mode. See
git history for details.
