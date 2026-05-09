#!/usr/bin/env bash
#
# Install the bgutil-ytdlp-pot-provider companion. This is an upstream-required
# compatibility layer for recent yt-dlp versions; mixtape itself doesn't bypass
# anything — it just lets yt-dlp work the way the upstream project documents.
#
# Idempotent: safe to re-run. Updates the repo + node_modules if already cloned.
#
# Requirements:
#  - git
#  - deno (https://deno.land — installs npm deps itself, no Node needed)

set -e

# Allow override via XDG_DATA_HOME, otherwise default to user-local share dir.
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/mixtape"
SERVER_DIR="$DATA_DIR/bgutil-server"
REPO_URL="https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"

# Match the Python plugin major version so the JS server stays compatible.
# Update this when bumping bgutil-ytdlp-pot-provider in pyproject.toml.
REPO_REF="1.3.1"

if ! command -v git >/dev/null 2>&1; then
    echo "ERROR: git not found. Install git first." >&2
    exit 1
fi

if [ -d "$HOME/.deno/bin" ]; then
    export PATH="$HOME/.deno/bin:$PATH"
fi

if ! command -v deno >/dev/null 2>&1; then
    echo "ERROR: deno not found in PATH." >&2
    echo "Install: curl -fsSL https://deno.land/install.sh | sh" >&2
    exit 1
fi

mkdir -p "$DATA_DIR"

if [ ! -d "$SERVER_DIR/.git" ]; then
    echo "▶ Cloning bgutil-ytdlp-pot-provider into $SERVER_DIR (parent only — keeping just /server) …"
    TMP_CLONE=$(mktemp -d)
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$TMP_CLONE"
    rm -rf "$SERVER_DIR"
    mv "$TMP_CLONE/server" "$SERVER_DIR"
    # keep .git so we can re-pull in the future
    mv "$TMP_CLONE/.git" "$SERVER_DIR/.git" 2>/dev/null || true
    rm -rf "$TMP_CLONE"
else
    echo "▶ Repo already present at $SERVER_DIR — skipping clone."
fi

echo "▶ Installing JS deps via 'deno install' (~150 MB, one-time) …"
cd "$SERVER_DIR"
deno install --allow-scripts --entrypoint src/generate_once.ts

if [ -f "src/generate_once.ts" ] && [ -d "node_modules" ]; then
    echo "✔ bgutil companion ready at $SERVER_DIR"
else
    echo "✗ Setup incomplete — script or node_modules missing." >&2
    exit 1
fi
