# mixtape

> ⚠️ **Beta — `0.1.0b2`** · daemon-and-clients architecture; expect
> rough edges, please file issues.

> Mixtapes for the streaming era — a **headless background daemon**
> that syncs curated YouTube Music playlists onto USB MP3 players,
> with thin clients (terminal TUI for SSH/RPi, native Qt UI for
> Windows / macOS) when you actually need to touch it.

## Why this exists

Younger and older folks alike spend their days glued to their phone — even
to listen to music. **mixtape** exists to make music easy to enjoy *outside*
the phone, so you can put the screen down and pick up something else: a
small dedicated MP3 player handed to a kid for the car ride, an old
Walkman-style device on the dock by the bed, a USB stick plugged into the
hi-fi. Curate your playlists once, plug a device, walk away.

## What it does

Plug a registered device → it's auto-detected by its `.mixtape` marker,
synced (with per-playlist audio format), the filesystem is flushed, and you
get a "safe to unplug" notification. Designed to run **fully unattended**
under systemd (Linux/RPi), launchd (macOS) or the user Startup folder
(Windows).

Cross-platform: **Linux · Windows · macOS**. Python + FastAPI daemon +
Textual TUI + optional PySide6 desktop UI + yt-dlp + Deno.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│  mixtape-daemon (always running)                           │
│  Python + asyncio + FastAPI on 127.0.0.1:<ephemeral>       │
│                                                            │
│   services/  SyncService · LibraryService · WatcherService │
│              CookieService · BgutilService · UpdateService │
│   api.json   port + bearer token (chmod 600)               │
└────────────────────────────────────────────────────────────┘
            ▲                          ▲
            │  HTTP + WebSocket        │
   ┌────────┴───────┐         ┌────────┴────────────┐
   │ Textual TUI    │         │ PySide6 + Qt tray   │
   │ Linux server,  │         │ Windows + macOS     │
   │ Linux desktop, │         │                     │
   │ RPi via SSH    │         │ window + native     │
   │                │         │ system-tray icon /  │
   │ default `mix-  │         │ macOS menu bar.     │
   │ tape` command  │         │ `mixtape --desktop` │
   └────────────────┘         └─────────────────────┘
```

The daemon is the brain, every client is replaceable. UIs hold no
domain state — they fetch state via REST and subscribe to a WebSocket
event stream for live updates (sync progress, USB plug events, cookie
expiry).

**Daily use is headless.** The clients are for the moments you genuinely
need a human:

- registering a new library / device,
- adding or editing playlists,
- refreshing expired cookies (≈ once a month),
- browsing the sync log when something looks off.

For remote setups you can do everything over SSH:
`ssh pi@rpi 'mixtape'` opens the TUI inside your terminal session,
`ssh pi@rpi 'mixtape --set-cookies' < cookies.txt` refreshes credentials
without ever touching the Pi.

## Disclaimer

`mixtape` is a personal-use tool for managing music libraries on hardware
you own, working with content you have legitimate access to.
**You are responsible for complying with the terms of service of any
platform you access and with applicable copyright law in your jurisdiction.**

This project does not circumvent any access controls. Audio retrieval uses
standard `yt-dlp` client APIs with session credentials (cookies) the user
provides themselves from their own logged-in browser session. The optional
`bgutil-ytdlp-pot-provider` companion is an upstream-required compatibility
layer used as documented by that project — it is not a bypass.

The project is not affiliated with, endorsed by, or sponsored by YouTube,
Google LLC, or any other music service. *YouTube* is a trademark of Google
LLC and is used here only for nominative description. *Raspberry Pi* is a
trademark of the Raspberry Pi Foundation.

No telemetry leaves your machine. Drive labels and volume detection are
entirely local.

## Features

- **Multiple libraries** — same playlist definitions, separate state on PC and on each USB device. Switch with `l`.
- **Auto USB detection** — when a registered device is plugged in, mixtape auto-switches the active library and syncs.
- **Per-playlist format** — choose `mp3`, `m4a`, `opus` or `flac` per playlist, with a quality preset.
- **Stable numbering** — every track keeps the same `NNN -` prefix across syncs; reordering on YouTube renames files in place (no re-download).
- **Best available audio** — `bestaudio/best` selector with codec-aware fallback (no double-transcode when the source matches your target format).
- **Safe-unplug flush** — `os.sync()` after every sync run, plus a notification once the data is physically on disk.
- **Headless / RPi mode** — `mixtape --headless`, suitable for a systemd user service.

## Install

A **single command** in your terminal — no manual download needed.

### Linux / Raspberry Pi

```bash
# Just install (TUI usable immediately; daemon spawns on first launch)
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash

# Recommended: also install a systemd --user unit so the daemon runs at boot
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --systemd
```

### macOS

```bash
# Homebrew is required (https://brew.sh)
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash

# Recommended: also install a LaunchAgent so the daemon runs at login
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --launchd

# Add the desktop GUI (PySide6 + Qt; ~60 MB)
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --launchd --desktop
```

### Windows

```powershell
# TUI + daemon at logon (default)
irm https://raw.githubusercontent.com/cinhil/mixtape/main/install.ps1 | iex

# Add the desktop GUI (PySide6 + Qt)
iex "& {$(irm https://raw.githubusercontent.com/cinhil/mixtape/main/install.ps1)} -Desktop"
```

(Detailed step-by-step with troubleshooting:
**[docs/INSTALL-WINDOWS.md](docs/INSTALL-WINDOWS.md)**)

### What the installer does

1. Installs prerequisites — `ffmpeg`, `git`, `python`, `uv`, `deno` —
   via your platform's package manager (`apt` on Linux, `brew` on
   macOS, `winget` on Windows; user-local where possible).
2. Clones the project to `~/.local/share/mixtape-app` (Linux/macOS) or
   `%LOCALAPPDATA%\Programs\mixtape` (Windows).
3. Sets up the optional bgutil companion.
4. Installs Python deps via `uv sync`. With `--desktop` (Linux/macOS) or
   `-Desktop` (Windows), also pulls PySide6 + qasync for the GUI.
5. Optionally installs a service to run the **daemon** at boot/login:
   - Linux:   `--systemd`  → user systemd unit
   - macOS:   `--launchd`  → LaunchAgent in `~/Library/LaunchAgents/`
   - Windows: default      → `Startup\mixtape-daemon.lnk` (skip with `-NoAutostart`)
6. On update, restarts the running daemon so it picks up the new code.

Override the install location with `MIXTAPE_DIR=...` (Linux/macOS) or
`$env:MIXTAPE_DIR` (Windows). Re-run any time to update — idempotent.

### After install

- **TUI** (any platform):
  ```
  mixtape           # connects to daemon (auto-spawns one if needed)
  ```
- **Desktop GUI** (Windows / macOS / Linux desktop, requires `--desktop`):
  ```
  mixtape --desktop
  ```
- **Run daemon manually**:
  ```
  mixtape-daemon    # foreground; for systemd Type=simple / launchd
  ```

The daemon writes `state/api.json` (port + bearer token, `chmod 600`)
when it starts; clients read this to connect. Nothing else is needed
to bridge them.

### Updates

**Re-run the same one-liner** to update everything (the installer is
idempotent — it picks up new mixtape commits, refreshes yt-dlp, and bumps
the bgutil companion).

How often: re-run **whenever a sync starts failing on every track** — that's
almost always a yt-dlp staleness issue (YouTube changes its player JS
often). Otherwise, monthly is plenty.

### Channels: stable vs dev

By default the installer follows the **latest GitHub Release tag**
(stable). To track the `main` branch instead (cutting edge — what was just
committed):

```bash
# Linux
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --dev
```

```powershell
# Windows
iex "& {$(irm https://raw.githubusercontent.com/cinhil/mixtape/main/install.ps1)} -Dev"
```

You can also pin to a specific version with `--ref=vX.Y.Z` (Linux) or
`-Ref vX.Y.Z` (Windows, e.g.
`iex "& {$(irm …/install.ps1)} -Ref v0.1.0b1"`).

See [docs/RELEASING.md](docs/RELEASING.md) for the maintainer-side release
process (tagging, GitHub Actions, etc.).

### Cookies

Cookies expire roughly every 30 days. The TUI shows `✗ cookies expired` in
the status bar when that happens; press `c` to paste fresh ones from your
browser. Cookie status is refreshed at app start and after each sync.

#### Headless / Raspberry Pi: how to refresh cookies remotely

The headless service notices when cookies expire, logs a clear warning, and
touches a marker file at:

- Linux: `~/.local/state/mixtape/needs-cookies`
- (the file's content is the reason, e.g. `expired: …`)

To refresh from another machine, pipe the new cookies via SSH:

```bash
# On your laptop, after re-exporting cookies from the browser:
ssh pi@rpi 'mixtape --set-cookies' < cookies.txt
```

The remote command:
1. Validates the new cookies live (one quick API call)
2. Writes them to `~/.config/mixtape/cookies.txt` (chmod 600)
3. Removes the `needs-cookies` marker if validation succeeds

The next USB plug-in event triggers a normal sync — no service restart
needed (cookies are re-checked on every run).

You can also monitor the headless logs directly:

```bash
journalctl --user -u mixtape -f
```

In the TUI:
- `c` refresh cookies (paste via `mixtape --set-cookies` from your laptop)
- `s` sync the selected playlist · `S` sync all
- `r` reload state from the daemon
- `u` re-check for updates · `q` quit (the daemon stays running)

## Background mode — Qt window + native tray

For a "set and forget" experience on a desktop machine (Windows / macOS /
Linux desktop with a system tray), use the optional PySide6 GUI:

```bash
# After installing with --desktop / -Desktop
mixtape --desktop
```

A real Qt window with a playlist table, a status bar (cookies / bgutil
/ library / update), action buttons (Sync selected, Sync all, Refresh
cookies, Check update), and a live event log fed by the daemon's
WebSocket stream. The system-tray icon (or macOS menu-bar item — Qt
maps `QSystemTrayIcon` to NSStatusItem automatically) stays present
when the window is hidden:

- **Click the tray icon** → show the window.
- **Close the window** → with *Close to tray* enabled, the window
  hides and the daemon keeps running. Without it, the window closes
  but the daemon still runs (it's a separate process now).
- **Tray menu → Quit** → also stops the daemon.

The whole UI is one process (Qt + qasync — no IPC trickery, no PID-file
ceremony), and the daemon is a separate long-running process — so
shutting the GUI does not kill the watcher.

## Headless / Raspberry Pi

The daemon is the headless service. Run it as a `systemd --user` unit;
the install script handles this for you when you pass `--systemd`:

```bash
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --systemd
journalctl --user -u mixtape -f          # follow logs
systemctl --user restart mixtape         # apply config changes
```

The unit runs `mixtape-daemon` (`Type=simple`, restart-on-failure). It
watches for USB volumes; when one matches a registered library's
`.mixtape` marker UUID it switches the active library and auto-syncs
— only if cookies are still valid. Otherwise the sync is skipped and a
clear log line is emitted.

SSH into the Pi and `mixtape` opens the TUI in your terminal session;
all actions go through the daemon's local API, so you see live state
+ progress over the same SSH session.

## How it works

- **One folder per playlist** under each library root.
- A per-playlist `.archive` (yt-dlp's record of downloaded video IDs) and
  `.manifest.yaml` (track number ↔ filename mapping + the playlist's URL,
  format, and quality) drive incremental syncs.
- Re-orderings on YouTube are detected and trigger renames on disk, never
  re-downloads.

### Library layout — fully self-describing

Each library (a folder on a PC drive or a USB device) carries its own
identity and the metadata of every playlist it holds. There is **no
machine-specific state on the device** — plug it into another mixtape
installation and everything is rediscovered from disk:

```
<library-root>/
├── .mixtape                       # library identity (UUID + name)
├── sync.log                       # human-readable per-library sync history
├── Road Trip 2026/                # one folder per playlist
│   ├── .manifest.yaml             # url, format, quality, track ↔ file map
│   ├── .archive                   # yt-dlp's "already downloaded" record
│   ├── 001 - Artist - Track.m4a
│   ├── 002 - Artist - Track.m4a
│   └── …
├── Workout Mix/
│   ├── .manifest.yaml
│   ├── .archive
│   └── …
└── Chill Evening/
    └── …
```

**`.mixtape`** at the root holds the library's stable UUID — when you re-plug
the device on a different machine (drive letter changed, fresh mixtape
install), it's recognised by that UUID, not by volume label.

**`.manifest.yaml`** in each playlist folder is the playlist's own snapshot:
its YouTube URL, audio format, quality preset, the cookies-required flag,
and the per-track number ↔ filename mapping. That's enough for any mixtape
installation to re-import the playlist without consulting the user's
central config.

What this enables:
- Plug your USB MP3 player into a friend's mixtape: it's registered as a
  known library and you can keep syncing the same playlists from there.
- Move from PC to Raspberry Pi: install mixtape on the RPi, plug the
  device, hit "register" — every playlist appears with its existing
  numbering and audio files preserved.
- Multiple devices side-by-side: each one has its own UUID and its own
  playlist set; mixtape switches the *active* library on plug-in.

## TUI key bindings

| Key | Action |
|-----|--------|
| `s` / `S` | Sync selected / Sync all |
| `c` | Refresh cookies (status check) |
| `u` | Re-check for updates |
| `r` | Reload state from the daemon |
| `q` | Quit (the daemon stays running) |

Add / edit / delete playlist forms are coming back in the next pass —
the daemon already exposes `LibraryService` REST endpoints; the screens
are a port, not a rewrite.

## System dependencies

- `ffmpeg` — audio re-encoding and tag/thumbnail embedding (apt /
  brew / winget)
- `deno` — JavaScript runtime used by the bgutil-ytdlp-pot-provider
  companion (installed user-local under `~/.deno/bin` on
  Linux/macOS, via winget on Windows)
- `git` — for `setup-bgutil.sh` and update pulls

Linux:   `sudo apt install ffmpeg git && curl -fsSL https://deno.land/install.sh | sh`
macOS:   `brew install ffmpeg git deno`
Windows: `winget install Gyan.FFmpeg Git.Git DenoLand.Deno` (or run install.ps1)

## Optional companion (`bgutil-ytdlp-pot-provider`)

Recent `yt-dlp` versions optionally cooperate with the
[`bgutil-ytdlp-pot-provider`](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
project for full compatibility with upstream API changes. Mixtape integrates
it via yt-dlp's standard plugin interface; it's optional and entirely local.

`./setup-bgutil.sh` clones that upstream project to
`~/.local/share/mixtape/bgutil-server/` and uses Deno to install its npm
dependencies (Deno handles npm packages itself — no Node installation
required). At app launch a local HTTP daemon is started on
`127.0.0.1:4416`; yt-dlp discovers it automatically. The daemon is shut down
cleanly when the app exits.

## Storage

All state lives in standard XDG locations on Linux/macOS and the
matching `%APPDATA%` / `%LOCALAPPDATA%` dirs on Windows. The daemon is
the only writer; clients connect over HTTP and don't poke at these
files directly.

| Path | Contents |
|------|----------|
| `~/.config/mixtape/` (Linux/macOS) · `%APPDATA%\mixtape\` (Windows) | `config.yaml`, `cookies.txt` |
| `~/.local/share/mixtape/` (Linux/macOS) · `%LOCALAPPDATA%\mixtape\` (Windows) | `bgutil-server/` companion |
| `~/.local/state/mixtape/` (Linux/macOS) · `%LOCALAPPDATA%\mixtape\state\` (Windows) | `api.json` (daemon discovery), `bgutil-server.log` |
| `~/Library/Logs/mixtape-daemon.log` (macOS only) | LaunchAgent stdout/stderr |
| `<library>/sync.log` | Per-library sync history |
| `<library>/<playlist>/.archive` · `.manifest.yaml` | Per-playlist sync state |

## Local API

The daemon exposes a small REST + WebSocket API on `127.0.0.1:<ephemeral>`,
authenticated with a 256-bit bearer token written to
`state/api.json` (`chmod 600`). Both port and token are minted fresh
at every daemon start.

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/status` | bgutil / cookies / sync / update snapshot |
| `GET`  | `/libraries` | active library + list + close-to-tray flag |
| `GET`  | `/playlists` | playlists in the active library |
| `POST` | `/sync` | start a sync (body: `{library?, playlists?}`) |
| `POST` | `/sync/cancel` | request mid-sync cancellation |
| `POST` | `/cookies/refresh` | force a cookie revalidation |
| `POST` | `/update/refresh` · `/update/apply` | check / apply mixtape update |
| `POST` | `/shutdown` | stop the daemon |
| `WS`   | `/events` | live event stream (sync.*, library.*, …) |

OpenAPI docs are live at `http://<host>:<port>/docs` while the daemon
runs.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
