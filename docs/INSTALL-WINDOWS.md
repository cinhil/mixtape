# Installing mixtape on Windows

Step-by-step guide for a fresh Windows 10 (1809+) or Windows 11 machine.
The full install takes about 10 minutes the first time.

> If anything below fails, jump to [Troubleshooting](#troubleshooting) at the
> bottom — common issues are all listed there.

---

## 1. Install the prerequisites

Open **PowerShell** (Start menu → "PowerShell"). You don't need Administrator
mode for any of this — everything installs into your user profile.

### 1a. Install via `winget` (recommended)

`winget` is the official Windows package manager. Run these one by one:

```powershell
winget install --id Python.Python.3.12 -e
winget install --id astral-sh.uv -e
winget install --id Gyan.FFmpeg -e
winget install --id DenoLand.Deno -e
winget install --id Git.Git -e
```

Each installer runs silently. Accept the license when prompted.

> **Important:** after the last `winget install`, **close PowerShell and open
> a new window**. The new tools won't be on your `PATH` until you do.

### 1b. If `winget` isn't available

If `winget` isn't recognised, install it from the Microsoft Store
("App Installer") or use these alternatives:

| Tool | Manual install |
|------|----------------|
| Python 3.12 | https://www.python.org/downloads/ — **tick "Add Python to PATH"** during the installer |
| `uv` | `irm https://astral.sh/uv/install.ps1 | iex` |
| ffmpeg | https://www.gyan.dev/ffmpeg/builds/ → download "release essentials" zip → extract → add the `bin\` folder to your PATH |
| Deno | `irm https://deno.land/install.ps1 | iex` |
| Git | https://git-scm.com/download/win |

### 1c. Verify everything is installed

In a fresh PowerShell:

```powershell
python --version    # → Python 3.12.x
uv --version        # → uv 0.x.x
ffmpeg -version     # → ffmpeg version 7.x
deno --version      # → deno 2.x.x
git --version       # → git version 2.x.x
```

If any of these say "not recognised", re-open PowerShell once more or check
the troubleshooting section.

---

## 2. Get the project

Pick a folder where you want mixtape to live (e.g. `C:\Users\you\Projects\`):

```powershell
mkdir $HOME\Projects -Force
cd $HOME\Projects
git clone https://github.com/cinhil/mixtape.git
cd mixtape
```

(Use `https://` rather than `git@github.com:` unless you've already set up an
SSH key on this machine.)

---

## 3. Install the Python dependencies

```powershell
uv sync
```

This downloads `textual`, `yt-dlp` (latest from upstream), `pyyaml`,
`mutagen`, and `bgutil-ytdlp-pot-provider` into a local `.venv`. Takes about
30 seconds.

---

## 4. Install the optional bgutil companion

This unlocks full upstream compatibility with recent yt-dlp versions:

```powershell
.\setup-bgutil.ps1
```

What it does:
- Clones the upstream `bgutil-ytdlp-pot-provider` project to
  `%LOCALAPPDATA%\mixtape\bgutil-server\`
- Uses Deno to install ~150 MB of npm dependencies (Deno handles npm by
  itself — no Node.js installation needed)
- Idempotent: safe to re-run later to update

---

## 5. First launch

```powershell
.\run.ps1
```

You should see the mixtape TUI. The status bar shows the current state —
expect to see something like:

```
0 playlist(s) — ✗ no cookies (sync blocked) — press 'c' — ✓ bgutil companion — library: PC
```

Two things to set up before your first sync:

### 5a. Paste your YouTube cookies

This authenticates the downloader as your account, the same way your browser
does:

1. Install the **"Get cookies.txt LOCALLY"** browser extension
   ([Chrome](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) ·
   [Firefox](https://addons.mozilla.org/firefox/addon/cookies-txt-one-click/))
2. Go to https://music.youtube.com (logged in)
3. Click the extension icon → **Export** for *this site*
4. The clipboard now has your cookies
5. In the mixtape TUI, press `c`, paste with **Ctrl+V** in the textarea, then
   **Ctrl+S** to save

The status bar should change to `✓ cookies valid` after a few seconds.

### 5b. Add a playlist

Press `a` → paste a YouTube Music playlist URL → press the *Récupérer le
titre* button → pick a format (`mp3` for old players, `m4a` for newer) and
quality → save. Repeat for each playlist.

Or import all your library playlists at once: press `i`.

### 5c. Sync

Pick a playlist with the arrow keys, press `s` (selected) or `S` (all).
First-time sync downloads everything; subsequent syncs only fetch new tracks.

---

## 6. Add your USB MP3 player as a library

When the device is plugged in:

1. Press `l` (Libraries screen)
2. Press `u` (register USB)
3. Pick the drive from the dropdown (e.g. `D: MP3-player`)
4. Browse to the folder that should hold your playlists (typically
   `D:\music`). Each playlist becomes a subfolder under it.
5. Tick **Auto-sync when this device is plugged in**
6. Save

From now on: plug the device → mixtape detects it by its volume label →
switches the active library to it → syncs all playlists → flushes the
filesystem → notifies you it's safe to unplug.

---

## 7. Daily use

To launch the TUI:

```powershell
cd $HOME\Projects\mixtape
.\run.ps1
```

You can also create a Windows Terminal profile or a desktop shortcut that
points to `pwsh.exe -Command "cd $HOME\Projects\mixtape; .\run.ps1"`.

To update mixtape later:

```powershell
cd $HOME\Projects\mixtape
git pull
uv sync
```

To update the bgutil companion:

```powershell
.\setup-bgutil.ps1
```

---

## Where files live

You shouldn't need to touch these — the TUI manages everything:

| Path | What's there |
|------|--------------|
| `%APPDATA%\mixtape\config.yaml` | Libraries, playlists, defaults |
| `%APPDATA%\mixtape\cookies.txt` | YouTube cookies (sensitive — don't share) |
| `%LOCALAPPDATA%\mixtape\bgutil-server\` | Deno companion + npm deps |
| `%LOCALAPPDATA%\mixtape\state\bgutil-server.log` | Companion daemon log |
| `<library>\sync.log` | Per-library sync history (one line per track) |
| `<library>\<playlist>\.archive`, `.manifest.yaml` | Per-playlist sync state |

Tip: paste `%APPDATA%\mixtape` in the Explorer address bar to open the
config folder.

---

## Troubleshooting

### "winget is not recognized"

Update Windows or install **App Installer** from the Microsoft Store.

### "uv : The term 'uv' is not recognized"

Close and re-open PowerShell. If it still fails:

```powershell
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
```

Add that path permanently in **Settings → System → About → Advanced system
settings → Environment Variables**.

### `.\run.ps1` says "running scripts is disabled on this system"

Allow signed-or-local PowerShell scripts for your user only:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Confirm with `Y`. This only affects your account.

### "deno not found in PATH"

After `winget install DenoLand.Deno`, the binary lives at
`%USERPROFILE%\.deno\bin\deno.exe`. The launcher (`run.ps1`) adds this to
PATH automatically. If you're calling `deno` directly outside the launcher:

```powershell
$env:Path = "$env:USERPROFILE\.deno\bin;$env:Path"
```

### Cookies stop working after a few weeks

YouTube rotates the `LOGIN_INFO` cookie about every 30 days. Re-export from
the browser extension and paste again with `c`. The status bar in the TUI
shows you when this happens (`✗ cookies expired (sync blocked)`).

### USB device isn't detected on plug-in

The detection runs every 5 seconds. Press `l` to confirm the device's
volume label matches what's stored. If you renamed the volume in Windows,
edit the library or re-register it (`d` to remove, `u` to register again).

### Audio quality looks lower than expected

Check the per-track `Source:` line in the sync log — it tells you what
yt-dlp picked (e.g. `Opus 135k`, `AAC 256k`, …). The format depends on what
YouTube exposes for your authenticated session and on whether the bgutil
companion is running. The status bar should say `✓ bgutil companion`.

### "Video unavailable" on some tracks

Some tracks in YouTube Music playlists point to video IDs that have been
removed or restricted. You can't reach those programmatically; the failure
summary at the end of a sync lists each one with a clickable
`https://music.youtube.com/watch?v=…` link so you can fix the playlist
manually in the YouTube Music app.
