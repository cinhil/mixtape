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
#
# Compatibility: works on Windows PowerShell 5.1 (the default Windows ships)
# AND PowerShell 7+. Avoid PS 7-only operators (??, ?., ?:, &&, ||).

[CmdletBinding()]
param(
    [switch]$NoShortcut,
    [switch]$NoAutostart,
    [switch]$Desktop,    # install the optional PySide6 GUI
    [switch]$Dev,
    [string]$Ref
)

$ErrorActionPreference = 'Stop'

# PowerShell-Stop trap: native commands (uv, git, deno, …) routinely write
# progress lines to stderr *on success*. With $ErrorActionPreference='Stop',
# PS wraps each stderr write as a terminating ErrorRecord — even `2>&1`
# doesn't escape it, because the error fires before the merge. Wrap any
# native invocation in this helper to relax EAP for that one call; we still
# rely on $LASTEXITCODE afterwards to detect real failures.
function Invoke-Native {
    param([Parameter(Mandatory=$true)][scriptblock]$Block)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block } finally { $ErrorActionPreference = $prev }
}

# Force TLS 1.2 for any Invoke-RestMethod / Invoke-WebRequest calls — needed
# on a freshly-installed Windows PowerShell 5.1 whose default protocol is
# still TLS 1.0/1.1, which GitHub now refuses. No-op on PS 7+.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

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
    Invoke-Native { & winget install --id $p.Id -e --accept-package-agreements --accept-source-agreements --silent 2>&1 } | Out-Null
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
    Invoke-Native { & git -C $InstallDir fetch --tags --prune origin 2>&1 } | Write-Host
    Invoke-Native { & git -C $InstallDir checkout --quiet $TargetRef 2>&1 } | Write-Host
    # If we're on a branch, fast-forward; if on a tag, checkout already moved.
    Invoke-Native { & git -C $InstallDir symbolic-ref --quiet HEAD 2>&1 } | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Invoke-Native { & git -C $InstallDir pull --ff-only 2>&1 } | Write-Host
    }
    $LASTEXITCODE = 0
    OK "Source at $TargetRef"
} else {
    Step "Cloning to $InstallDir ($TargetRef)"
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
    Invoke-Native { & git clone --branch $TargetRef $RepoUrl $InstallDir 2>&1 } | Write-Host
    if ($LASTEXITCODE -ne 0) {
        # Fallback (e.g. ref is a commit hash, not a branch/tag)
        Invoke-Native { & git clone $RepoUrl $InstallDir 2>&1 } | Write-Host
        Invoke-Native { & git -C $InstallDir checkout --quiet $TargetRef 2>&1 } | Out-Null
        $LASTEXITCODE = 0
    }
    OK "Cloned at $TargetRef"
}
Set-Location $InstallDir

# 3. Python deps --------------------------------------------------------------
Header "Step 3/5 — Python dependencies"
# Always pull the freshest yt-dlp (rev = "master" in pyproject is pinned by
# uv.lock; this is what actually updates it). Cheap when nothing changed.
#
# Why we use `2>&1` (merge) and a $LASTEXITCODE check instead of `2>$null`:
# uv writes its progress lines (e.g. "Resolved 27 packages in 1s") to stderr
# even on success. With $ErrorActionPreference='Stop' and `2>$null`, any
# stderr output from a native command becomes a NativeCommandError and kills
# the script — *even when uv exited 0*. Merging stderr into stdout and then
# only acting on $LASTEXITCODE keeps the install quiet on success and shows
# the full diagnostic on real failures.
Step "Refreshing yt-dlp from upstream master …"
$lockOut = Invoke-Native { & uv lock --upgrade-package yt-dlp 2>&1 }
if ($LASTEXITCODE -ne 0) {
    $lockOut | ForEach-Object { Write-Host $_ }
    Warn "uv lock --upgrade-package yt-dlp failed — keeping the previously-locked yt-dlp revision."
    Warn "Run the command above directly to see the full error and report it if it persists."
    $LASTEXITCODE = 0
}
if ($Desktop) {
    Step "uv sync --extra desktop (PySide6 + qasync — heavyweight) …"
    $syncOut = Invoke-Native { & uv sync --extra desktop 2>&1 }
} else {
    Step "uv sync …"
    $syncOut = Invoke-Native { & uv sync 2>&1 }
}
if ($LASTEXITCODE -ne 0) {
    $syncOut | ForEach-Object { Write-Host $_ }
    Fail "uv sync failed (see output above)"
}
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

    # Delete any existing shortcut first — Windows caches .lnk icons very
    # aggressively, so overwriting in place doesn't refresh the visible icon.
    if (Test-Path $shortcutPath) {
        try { Remove-Item -Force -Path $shortcutPath } catch { }
    }

    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    # Prefer PowerShell 7 (pwsh) when available, otherwise fall back to the
    # built-in Windows PowerShell. Avoid `??` so Windows PowerShell 5.1 can
    # parse this script too (the null-coalescing operator is PS 7+).
    $pwsh = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($pwsh) {
        $shortcut.TargetPath = $pwsh.Source
    } else {
        $shortcut.TargetPath = (Get-Command powershell.exe).Source
    }
    $shortcut.Arguments        = "-NoExit -ExecutionPolicy Bypass -File `"$launcher`""
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description      = 'mixtape — sync YT Music playlists to USB MP3 players'
    if (Test-Path $iconCandidate) { $shortcut.IconLocation = $iconCandidate }
    $shortcut.Save()

    # Ask the shell to refresh icon caches so the new icon shows up without
    # a logoff. Best-effort — silently ignore if either tool is missing.
    try { ie4uinit.exe -show 2>$null | Out-Null } catch { }
    try {
        $sig = '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);'
        $type = Add-Type -MemberDefinition $sig -Name 'Mixtape_SH' -Namespace Mx -PassThru -ErrorAction SilentlyContinue
        if ($type) { $type::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero) }
    } catch { }
    OK "Desktop shortcut created: $shortcutPath"
} else {
    Step "Skipping desktop shortcut (-NoShortcut)"
}

# 6. Daemon autostart at logon ------------------------------------------------
Header "Step 6 — daemon autostart at logon"
if (-not $NoAutostart) {
    $startupDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    $startupLnk = Join-Path $startupDir 'mixtape-daemon.lnk'
    New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
    if (Test-Path $startupLnk) {
        try { Remove-Item -Force -Path $startupLnk } catch { }
    }
    $pythonw = Join-Path $InstallDir '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path $pythonw)) {
        $pythonw = Join-Path $InstallDir '.venv\Scripts\python.exe'
    }
    $startupShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($startupLnk)
    $startupShortcut.TargetPath = $pythonw
    $startupShortcut.Arguments = "-m mixtape.daemon.main"
    $startupShortcut.WorkingDirectory = $InstallDir
    $startupShortcut.Description = 'mixtape daemon — background sync engine'
    $startupShortcut.WindowStyle = 7   # minimized; pythonw has no console anyway
    if (Test-Path $iconCandidate) { $startupShortcut.IconLocation = $iconCandidate }
    $startupShortcut.Save()
    OK "daemon autostart at logon: $startupLnk"
} else {
    Step "Skipping daemon autostart (-NoAutostart)"
}

# 7. Restart any running daemon so it picks up the new code ------------------
$running = Get-Process -Name pythonw, python -ErrorAction SilentlyContinue | Where-Object {
    try { $_.CommandLine -match 'mixtape.daemon' } catch { $false }
}
if ($running) {
    Step "Asking the running daemon to restart so it picks up the new code …"
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
}

# Spawn one fresh daemon now so the user has a working install immediately.
if (-not $NoAutostart) {
    Step "Starting daemon …"
    Start-Process -FilePath $pythonw -ArgumentList @("-m", "mixtape.daemon.main") `
        -WorkingDirectory $InstallDir -WindowStyle Hidden | Out-Null
    OK "daemon started"
}

Write-Host "`n✓ All done." -ForegroundColor Green
Write-Host "Project: $InstallDir"
Write-Host ""
Write-Host "Launch options:"
Write-Host "  TUI (default):    double-click 'mixtape' on your desktop"
Write-Host "  Daemon (manual):  & $pythonw -m mixtape.daemon.main"
if ($Desktop) {
    Write-Host "  Desktop GUI:      cd $InstallDir && uv run mixtape --desktop"
}
