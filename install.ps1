# mixtape — one-shot Windows installer.
#
# Run as a one-liner from any PowerShell window (no clone needed):
#
#   irm https://raw.githubusercontent.com/cinhil/mixtape/main/install.ps1 | iex
#
# Flags (when invoked with .\install.ps1):
#   -Dev          follow the 'main' branch (cutting edge) instead of the
#                 latest release tag (stable, the default)
#   -Ref X        pin to a specific tag, branch, or commit
#   -NoShortcut   skip the desktop shortcut step
#
# Default behaviour: install / update to the latest GitHub Release. If no
# release exists yet, falls back to 'main'.
#
# Override install location:  $env:MIXTAPE_DIR = "C:\path"; iex (irm …)
# Idempotent: safe to re-run (it pulls / checks out the target ref).

[CmdletBinding()]
param(
    [switch]$NoShortcut,
    [switch]$Dev,
    [string]$Ref
)

$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/cinhil/mixtape.git'
$RepoApi = 'https://api.github.com/repos/cinhil/mixtape/releases/latest'
$DefaultInstall = Join-Path $env:LOCALAPPDATA 'Programs\mixtape'
$InstallDir = if ($env:MIXTAPE_DIR) { $env:MIXTAPE_DIR } else { $DefaultInstall }

function Resolve-Ref {
    if ($Ref) { return $Ref }
    if ($Dev) { return 'main' }
    try {
        $r = Invoke-RestMethod -Uri $RepoApi -ErrorAction Stop
        if ($r.tag_name) { return $r.tag_name }
    } catch { }
    return 'main'  # no releases yet → fall back
}
$TargetRef = Resolve-Ref

function Header($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Step($msg)   { Write-Host "  → $msg" -ForegroundColor White }
function OK($msg)     { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Warn($msg)   { Write-Warning $msg }
function Fail($msg)   { Write-Error $msg; exit 1 }

# Detect: are we already inside a mixtape checkout?
$LocalMode = $false
if ((Test-Path 'pyproject.toml') -and
    (Select-String -Path 'pyproject.toml' -Pattern '^name = "mixtape"' -Quiet)) {
    $InstallDir = (Get-Location).Path
    $LocalMode  = $true
}

# Refresh PATH from registry so freshly-installed tools become visible
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
    $deno = Join-Path $env:USERPROFILE '.deno\bin'
    if (Test-Path $deno) { $env:Path = "$deno;$env:Path" }
    $uv = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path $uv)   { $env:Path = "$uv;$env:Path" }
}

# 1. Prerequisites ------------------------------------------------------------
Header "Step 1/5 — prerequisites (winget)"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail @"
winget not found. Install 'App Installer' from the Microsoft Store, then re-run.
On Windows 11 / 10 (1809+) winget is normally pre-installed.
"@
}
$prereqs = @(
    @{ Id = 'Python.Python.3.12'; Cmd = 'python'; Display = 'Python 3.12' }
    @{ Id = 'astral-sh.uv';        Cmd = 'uv';     Display = 'uv (Python pkg manager)' }
    @{ Id = 'Gyan.FFmpeg';          Cmd = 'ffmpeg'; Display = 'ffmpeg' }
    @{ Id = 'DenoLand.Deno';        Cmd = 'deno';   Display = 'Deno' }
    @{ Id = 'Git.Git';              Cmd = 'git';    Display = 'Git' }
)
foreach ($p in $prereqs) {
    if (Get-Command $p.Cmd -ErrorAction SilentlyContinue) {
        OK "$($p.Display) already installed"
        continue
    }
    Step "Installing $($p.Display) …"
    winget install --id $p.Id -e --accept-package-agreements --accept-source-agreements --silent | Out-Null
    Refresh-Path
    if (Get-Command $p.Cmd -ErrorAction SilentlyContinue) {
        OK "$($p.Display) installed"
    } else {
        Warn "$($p.Display) installed but not yet on PATH — re-open PowerShell if subsequent steps fail."
    }
}

# 2. Clone (or pull / checkout target ref) -----------------------------------
Header "Step 2/5 — project source"
$channel = if ($Dev -or ($TargetRef -eq 'main')) { '(dev)' } else { '(stable)' }
Step "Target ref: $TargetRef $channel"
if ($LocalMode) {
    OK "Running from existing checkout: $InstallDir"
} elseif (Test-Path (Join-Path $InstallDir '.git')) {
    Step "Updating existing clone at $InstallDir"
    git -C $InstallDir fetch --tags --prune origin
    git -C $InstallDir checkout --quiet $TargetRef
    # If we're on a branch, fast-forward; if on a tag, checkout already moved.
    git -C $InstallDir symbolic-ref --quiet HEAD *> $null
    if ($LASTEXITCODE -eq 0) {
        git -C $InstallDir pull --ff-only
    }
    $LASTEXITCODE = 0
    OK "Source at $TargetRef"
} else {
    Step "Cloning to $InstallDir ($TargetRef)"
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
    git clone --branch $TargetRef $RepoUrl $InstallDir 2>$null
    if ($LASTEXITCODE -ne 0) {
        # Fallback (e.g. ref is a commit hash, not a branch/tag)
        git clone $RepoUrl $InstallDir
        git -C $InstallDir checkout --quiet $TargetRef 2>$null
        $LASTEXITCODE = 0
    }
    OK "Cloned at $TargetRef"
}
Set-Location $InstallDir

# 3. Python deps --------------------------------------------------------------
Header "Step 3/5 — Python dependencies"
# Always pull the freshest yt-dlp (rev = "master" in pyproject is pinned by
# uv.lock; this is what actually updates it). Cheap when nothing changed.
Step "Refreshing yt-dlp from upstream master …"
uv lock --upgrade-package yt-dlp 2>$null | Out-Null
Step "uv sync …"
uv sync
OK "Python deps up to date"

# 4. bgutil companion ---------------------------------------------------------
Header "Step 4/5 — bgutil companion (~150 MB, one-time)"
& (Join-Path $InstallDir 'setup-bgutil.ps1')
OK "bgutil companion ready"

# 5. Desktop shortcut ---------------------------------------------------------
if (-not $NoShortcut) {
    Header "Step 5/5 — desktop shortcut"
    $WshShell      = New-Object -ComObject WScript.Shell
    $shortcutPath  = Join-Path ([Environment]::GetFolderPath('Desktop')) 'mixtape.lnk'
    $launcher      = Join-Path $InstallDir 'run.ps1'
    $iconCandidate = Join-Path $InstallDir 'mixtape.ico'
    $shortcut      = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source `
                            ?? (Get-Command powershell.exe).Source
    $shortcut.Arguments        = "-NoExit -ExecutionPolicy Bypass -File `"$launcher`""
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description      = 'mixtape — sync YT Music playlists to USB MP3 players'
    if (Test-Path $iconCandidate) { $shortcut.IconLocation = $iconCandidate }
    $shortcut.Save()
    OK "Desktop shortcut created: $shortcutPath"
} else {
    Step "Skipping desktop shortcut (-NoShortcut)"
}

Write-Host "`n✓ All done." -ForegroundColor Green
Write-Host "Project: $InstallDir"
Write-Host "Launch:  double-click 'mixtape' on your desktop  —  or run  $InstallDir\run.ps1"
