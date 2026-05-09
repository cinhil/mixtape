# Install the bgutil-ytdlp-pot-provider companion (Windows port of setup-bgutil.sh).
# Idempotent: safe to re-run.
#
# Requirements:
#   - git
#   - deno (https://deno.land — installs npm deps itself, no Node needed)

$ErrorActionPreference = 'Stop'

$DataDir   = if ($env:XDG_DATA_HOME) { Join-Path $env:XDG_DATA_HOME 'mixtape' } else { Join-Path $env:LOCALAPPDATA 'mixtape' }
$ServerDir = Join-Path $DataDir 'bgutil-server'
$RepoUrl   = 'https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git'
# Match the Python plugin major version. Bump when bgutil-ytdlp-pot-provider is bumped in pyproject.toml.
$RepoRef   = '1.3.1'

function Need-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Error "$name not found in PATH. Install it first."
        exit 1
    }
}

# Ensure deno is on PATH if installed user-locally.
$DenoBin = Join-Path $env:USERPROFILE '.deno\bin'
if (Test-Path $DenoBin) { $env:Path = "$DenoBin;$env:Path" }

Need-Cmd git
Need-Cmd deno

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

if (-not (Test-Path (Join-Path $ServerDir '.git'))) {
    Write-Host "▶ Cloning bgutil-ytdlp-pot-provider into $ServerDir (server/ only) …"
    $Tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "bgutil-clone-$(Get-Random)")
    git clone --depth 1 --branch $RepoRef $RepoUrl $Tmp.FullName | Out-Null
    if (Test-Path $ServerDir) { Remove-Item -Recurse -Force $ServerDir }
    Move-Item (Join-Path $Tmp 'server') $ServerDir
    if (Test-Path (Join-Path $Tmp '.git')) {
        Move-Item (Join-Path $Tmp '.git') (Join-Path $ServerDir '.git') -ErrorAction SilentlyContinue
    }
    Remove-Item -Recurse -Force $Tmp
} else {
    Write-Host "▶ Repo already present at $ServerDir — skipping clone."
}

Write-Host "▶ Installing JS deps via 'deno install' (~150 MB, one-time) …"
Push-Location $ServerDir
try {
    $env:DENO_NO_PROMPT = '1'
    $env:DENO_NO_UPDATE_CHECK = '1'
    deno install --allow-scripts --entrypoint src/generate_once.ts
} finally {
    Pop-Location
}

if ((Test-Path (Join-Path $ServerDir 'src\generate_once.ts')) -and
    (Test-Path (Join-Path $ServerDir 'node_modules'))) {
    Write-Host "✔ bgutil companion ready at $ServerDir"
} else {
    Write-Error "Setup incomplete — script or node_modules missing."
    exit 1
}
