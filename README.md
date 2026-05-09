# mixtape

> ⚠️ **Beta — `0.1.0b1`** · works on the author's setup but lightly tested.
> Expect rough edges, please file issues.

> Mixtapes for the streaming era — a TUI that mirrors curated YouTube Music
> playlists onto USB MP3 players.

Plug a registered device → it's auto-detected, recognised by its volume label,
synced (with per-playlist audio format), the filesystem is flushed, and you
get a "safe to unplug" notification. Designed to run **fully unattended** as a
systemd service on a Raspberry Pi.

Cross-platform (Linux · Windows). Python + Textual + yt-dlp + Deno.

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
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash
```

For an unattended auto-sync setup (RPi as a service):

```bash
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --systemd
```

### Windows

```powershell
irm https://raw.githubusercontent.com/cinhil/mixtape/main/install.ps1 | iex
```

(Detailed step-by-step with troubleshooting:
**[docs/INSTALL-WINDOWS.md](docs/INSTALL-WINDOWS.md)**)

### What the installer does

1. Installs prerequisites — `ffmpeg`, `git`, `python`, `uv`, `deno` — via your
   platform's package manager (`apt` / `winget`, user-local where possible)
2. Clones the project to `~/.local/share/mixtape-app` (Linux) or
   `%LOCALAPPDATA%\Programs\mixtape` (Windows)
3. Sets up the optional bgutil companion
4. Linux: optionally enables a `systemd --user` service ; Windows: creates a
   desktop shortcut

Override the install location with the `MIXTAPE_DIR` env var.
Re-run any time to update — it just `git pull`s.

### After install — launch the TUI

- **Windows**: double-click the *mixtape* shortcut on your desktop
- **Linux**: `cd ~/.local/share/mixtape-app && ./run.sh`

In the TUI:
- `c` paste cookies (use a browser extension like *Get cookies.txt LOCALLY*)
- `a` add a playlist (paste URL → title auto-fetched)
- `l` manage libraries (the PC default is created automatically; press `u` to register a USB device)
- `s` sync the selected playlist · `S` sync all

## Headless / Raspberry Pi

```bash
uv run mixtape --headless
```

Or as a systemd user service (auto-starts at boot, watches USB plug events):

```bash
cp mixtape.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mixtape.service
journalctl --user -u mixtape.service -f
```

The service watches for USB volumes; when one matches a registered library's
label, it switches the active library and runs an auto-sync — only if cookies
are still valid. Otherwise the sync is skipped and a clear log line is
emitted.

## How it works

- **One folder per playlist** under each library root (e.g.
  `~/Music/mixtape/<playlist>/` or `/media/<user>/<USB>/<playlist>/`).
- A per-playlist `.archive` (yt-dlp's record of downloaded video IDs) and
  `.manifest.yaml` (track number ↔ filename mapping) drive incremental syncs.
- Re-orderings on YouTube are detected and trigger renames on disk, never
  re-downloads.

## TUI key bindings (main screen)

| Key | Action |
|-----|--------|
| `a` / `e` / `d` | Add / edit / delete playlist |
| `s` / `S` | Sync selected / Sync all |
| `c` | Paste or update cookies |
| `i` | Import all your YouTube playlists in one go (cookies required) |
| `l` | Open the libraries screen |
| `r` | Reload `config.yaml` from disk |
| `q` | Quit |

## System dependencies

- `ffmpeg` — audio re-encoding and tag/thumbnail embedding
- `deno` — JavaScript runtime, used by yt-dlp to solve YouTube's player
  challenges since 2024
- (optional) `git` for `setup-bgutil.sh`

Linux: `sudo apt install ffmpeg && curl -fsSL https://deno.land/install.sh | sh`

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

All state lives in standard XDG locations. You shouldn't need to touch any of
these — the TUI manages everything.

| Path | Contents |
|------|----------|
| `~/.config/mixtape/` (Linux) · `%APPDATA%\mixtape\` (Windows) | `config.yaml`, `cookies.txt` |
| `~/.local/share/mixtape/` (Linux) · `%LOCALAPPDATA%\mixtape\` (Windows) | `bgutil-server/` companion |
| `~/.local/state/mixtape/` (Linux) · `%LOCALAPPDATA%\mixtape\state\` (Windows) | `bgutil-server.log` |
| `<library>/sync.log` | Per-library sync history |
| `<library>/<playlist>/.archive` · `.manifest.yaml` | Per-playlist sync state |

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
