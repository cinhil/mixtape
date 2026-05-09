#!/usr/bin/env bash
set -e
cd "$(dirname "$(readlink -f "$0")")"

# Ensure yt-dlp can find Deno for solving YouTube JS challenges (n-challenge,
# signature). Without it, audio downloads fail with "Only images are available".
if [ -d "$HOME/.deno/bin" ]; then
    export PATH="$HOME/.deno/bin:$PATH"
fi

if ! command -v deno >/dev/null 2>&1; then
    echo "WARNING: deno not found in PATH — YouTube downloads will likely fail." >&2
    echo "  Install: curl -fsSL https://deno.land/install.sh | sh" >&2
fi

# bgutil server (Premium streams) is optional but strongly recommended.
SERVER_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/mixtape/bgutil-server"
if [ ! -f "$SERVER_DIR/src/generate_once.ts" ] || [ ! -d "$SERVER_DIR/node_modules" ]; then
    echo "INFO: bgutil server not set up — downloads will fall back to public-quality streams (~135k)." >&2
    echo "  Run ./setup-bgutil.sh once to unlock Premium AAC 256k / Opus 266k." >&2
fi

exec uv run mixtape "$@"
