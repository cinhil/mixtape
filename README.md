# mixtape

> ⚠️ **Beta — `0.1.0b1`** · works on the author's setup but lightly tested.
> Expect rough edges, please file issues.

> Mixtapes for the streaming era — a TUI that mirrors curated YouTube Music
> playlists onto USB MP3 players.

Plug a registered device → it's auto-detected, recognised by its volume label,
synced (with per-playlist audio format), the filesystem is flushed, and you
get a "safe to unplug" notification. Designed to run **fully unattended** as a
systemd service on a Raspberry Pi.

Cross-platform (Linux · WSL · Windows). Python + Textual + yt-dlp + Deno.

## Disclaimer

`mixtape` is a personal-use tool to manage your own music libraries on
hardware you own. **You are responsible for complying with the terms of
service of any platform you access** and for using it only with content you
have legitimate rights to access. The project is not affiliated with YouTube,
Google, or any other music service. Drive letter, volume label, and platform
detection are entirely local — no telemetry leaves your machine.

## Features

- **Multiple libraries** — same playlist definitions, separate state on PC and on each USB device. Switch with `l`.
- **Auto USB detection** — when a registered device is plugged in, mixtape auto-switches the active library and syncs.
- **Per-playlist format** — choose `mp3`, `m4a`, `opus` or `flac` per playlist, with a quality preset.
- **Stable numbering** — every track keeps the same `NNN -` prefix across syncs; reordering on YouTube renames files in place (no re-download).
- **Premium-quality audio** — when the optional `bgutil-ytdlp-pot-provider` companion is installed, the audio stream selector picks the highest-bitrate format YouTube exposes for your account.
- **Safe-unplug flush** — `os.sync()` after every sync run, plus a notification once the data is physically on disk.
- **Headless / RPi mode** — `mixtape --headless`, suitable for a systemd user service.

## Quick start

```bash
uv sync                 # install Python deps
./setup-bgutil.sh       # one-time: install Deno-based audio resolution helper
./run.sh                # launch the TUI
```

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

## Audio resolution helper (`bgutil-ytdlp-pot-provider`)

Some YouTube audio streams require a *Proof-of-Origin token* since 2024.
Without it, downloads fall back to a public-quality tier (~135 kbps Opus).
The optional companion handles that token resolution locally.

`./setup-bgutil.sh` clones the upstream project to
`~/.local/share/mixtape/bgutil-server/` and uses Deno to install its npm
dependencies (Deno handles npm packages itself — no Node installation
required). At app launch a local HTTP daemon is started on
`127.0.0.1:4416`; yt-dlp discovers it automatically. The daemon is shut down
cleanly when the app exits.

## Config

`~/.config/mixtape/config.yaml` — editable by hand. Sample structure:

```yaml
defaults:
  format: mp3
  quality: '0'           # "0" = best VBR; "192" / "256" / "320" = CBR
active_library: PC
libraries:
  - name: PC
    path: /home/you/Music/mixtape
    volume_name: ""
    auto_sync: false
  - name: USB MP3 player
    path: /media/you/MP3-player/music
    volume_name: MP3-player
    auto_sync: true
playlists:
  - name: Road trip 2026
    url: https://music.youtube.com/playlist?list=…
    format: m4a
    quality: '0'
    relative_path: Road trip 2026
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
