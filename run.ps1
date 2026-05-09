# Launch mixtape on Windows. Mirror of run.sh.

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# Ensure deno is on PATH (yt-dlp uses it to solve YouTube's player challenges).
$DenoBin = Join-Path $env:USERPROFILE '.deno\bin'
if (Test-Path $DenoBin) { $env:Path = "$DenoBin;$env:Path" }

if (-not (Get-Command deno -ErrorAction SilentlyContinue)) {
    Write-Warning "deno not found in PATH — YouTube downloads will likely fail."
    Write-Warning "  Install via PowerShell:  irm https://deno.land/install.ps1 | iex"
}

# Optional bgutil companion (recommended for full upstream compatibility).
$DataDir   = if ($env:XDG_DATA_HOME) { Join-Path $env:XDG_DATA_HOME 'mixtape' } else { Join-Path $env:LOCALAPPDATA 'mixtape' }
$ServerDir = Join-Path $DataDir 'bgutil-server'
if (-not (Test-Path (Join-Path $ServerDir 'src\generate_once.ts')) -or
    -not (Test-Path (Join-Path $ServerDir 'node_modules'))) {
    Write-Host "INFO: bgutil companion not set up — run .\setup-bgutil.ps1 for full yt-dlp compatibility." -ForegroundColor Yellow
}

uv run mixtape @args
