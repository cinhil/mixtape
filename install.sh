#!/usr/bin/env bash
#
# mixtape — one-shot Linux / Raspberry Pi installer.
#
# Run as a one-liner from any terminal (no clone needed):
#
#   curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash
#
# Flags:
#   --systemd   also install a systemd --user service for unattended sync
#   --dev       follow the 'main' branch (cutting edge) instead of the latest
#               release tag (stable, the default)
#   --ref=X     pin to a specific tag, branch, or commit
#
# Default behaviour: install / update to the latest GitHub Release. If no
# release exists yet, falls back to 'main'.
#
# Override install location with: MIXTAPE_DIR=/some/path bash <(curl …)
# Idempotent: safe to re-run (it pulls / checks out the target ref).

set -e

REPO_URL="https://github.com/cinhil/mixtape.git"
REPO_API="https://api.github.com/repos/cinhil/mixtape/releases/latest"
DEFAULT_INSTALL="${MIXTAPE_DIR:-$HOME/.local/share/mixtape-app}"

NEED_SYSTEMD=0
USE_DEV=0
EXPLICIT_REF=""
for arg in "$@"; do
    case "$arg" in
        --systemd) NEED_SYSTEMD=1 ;;
        --dev)     USE_DEV=1 ;;
        --ref=*)   EXPLICIT_REF="${arg#*=}" ;;
        --help|-h)
            sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
    esac
done

# Resolve which git ref to install / update to.
#   --ref=foo       → that exact tag/branch/commit
#   --dev           → 'main' (cutting edge, what's just been committed)
#   default         → latest GitHub Release tag (stable), falls back to 'main'
#                     if there are no releases yet
resolve_ref() {
    if [ -n "$EXPLICIT_REF" ]; then
        echo "$EXPLICIT_REF"; return
    fi
    if [ "$USE_DEV" = "1" ]; then
        echo "main"; return
    fi
    local tag
    tag=$(curl -fsSL "$REPO_API" 2>/dev/null \
            | grep -m1 '"tag_name":' \
            | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/' || true)
    if [ -n "$tag" ]; then
        echo "$tag"
    else
        echo "main"
    fi
}
TARGET_REF="$(resolve_ref)"

cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
ok()    { printf "  \033[32m✓\033[0m %s\n" "$*"; }
step()  { printf "  → %s\n" "$*"; }
warn()  { printf "  \033[33m⚠\033[0m %s\n" "$*" >&2; }
fail()  { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }

# Detect: are we already inside a mixtape checkout?
if [ -f "pyproject.toml" ] && grep -q '^name = "mixtape"' pyproject.toml 2>/dev/null; then
    INSTALL_DIR="$PWD"
    LOCAL_MODE=1
else
    INSTALL_DIR="$DEFAULT_INSTALL"
    LOCAL_MODE=0
fi

# 1. apt prerequisites --------------------------------------------------------
cyan ""
cyan "=== Step 1/6 — system packages (apt) ==="
if ! command -v sudo >/dev/null 2>&1; then
    fail "sudo is required to install apt packages."
fi
need_apt=()
for pkg in ffmpeg git curl ca-certificates; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        ok "$pkg already installed"
    else
        need_apt+=("$pkg")
    fi
done
if [ "${#need_apt[@]}" -gt 0 ]; then
    step "sudo apt install -y ${need_apt[*]}"
    sudo apt update
    sudo apt install -y "${need_apt[@]}"
fi

# 2. Clone (or pull / checkout target ref) -----------------------------------
cyan ""
cyan "=== Step 2/6 — project source ==="
step "Target ref: $TARGET_REF $([ "$USE_DEV" = "1" ] && echo '(dev)' || echo '(stable)')"
if [ "$LOCAL_MODE" = "1" ]; then
    ok "Running from existing checkout: $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
    step "Updating existing clone at $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --tags --prune origin
    git -C "$INSTALL_DIR" checkout --quiet "$TARGET_REF"
    # If we're on a branch (e.g. main), fast-forward; if on a tag, checkout already moved us.
    if git -C "$INSTALL_DIR" symbolic-ref --quiet HEAD >/dev/null; then
        git -C "$INSTALL_DIR" pull --ff-only
    fi
    ok "Source at $TARGET_REF"
else
    step "Cloning to $INSTALL_DIR ($TARGET_REF)"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --branch "$TARGET_REF" "$REPO_URL" "$INSTALL_DIR" 2>/dev/null \
        || git clone "$REPO_URL" "$INSTALL_DIR"
    git -C "$INSTALL_DIR" checkout --quiet "$TARGET_REF" 2>/dev/null || true
    ok "Cloned at $TARGET_REF"
fi
cd "$INSTALL_DIR"

# 3. Deno (user-local) --------------------------------------------------------
cyan ""
cyan "=== Step 3/6 — Deno (JS runtime for yt-dlp) ==="
export PATH="$HOME/.deno/bin:$PATH"
if command -v deno >/dev/null 2>&1; then
    ok "deno already installed: $(deno --version | head -1)"
else
    step "Installing Deno into ~/.deno/bin (user-local) …"
    curl -fsSL https://deno.land/install.sh | sh
    export PATH="$HOME/.deno/bin:$PATH"
    ok "Deno installed"
fi

# 4. uv (user-local) ----------------------------------------------------------
cyan ""
cyan "=== Step 4/6 — uv (Python package manager) ==="
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
    ok "uv already installed: $(uv --version)"
else
    step "Installing uv into ~/.local/bin (user-local) …"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    ok "uv installed"
fi

# 5. Python deps + bgutil companion -------------------------------------------
cyan ""
cyan "=== Step 5/6 — Python deps + bgutil companion ==="
# Always pull the freshest yt-dlp (the rev = "master" entry in pyproject is
# pinned by uv.lock, so we need this for actual updates). Cheap when nothing
# has changed.
step "Refreshing yt-dlp from upstream master …"
uv lock --upgrade-package yt-dlp >/dev/null
step "uv sync …"
uv sync
ok "Python deps up to date"
step "Setting up / refreshing bgutil companion …"
./setup-bgutil.sh
ok "bgutil companion ready"

# 6. systemd unit (optional) --------------------------------------------------
cyan ""
cyan "=== Step 6/6 — systemd user service (optional) ==="
if [ "$NEED_SYSTEMD" = "1" ]; then
    target_dir="$HOME/.config/systemd/user"
    mkdir -p "$target_dir"
    # rewrite WorkingDirectory in case the install path differs from the template default
    sed "s|^WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|" mixtape.service \
        > "$target_dir/mixtape.service"
    systemctl --user daemon-reload
    systemctl --user enable --now mixtape.service
    ok "mixtape.service installed — see  journalctl --user -u mixtape -f"
else
    step "Skipping (pass --systemd to install the headless auto-sync service)"
fi

cyan ""
cyan "✓ All done."
echo "Project lives at: $INSTALL_DIR"
echo "Launch the TUI:   cd $INSTALL_DIR && ./run.sh"
if [ "$NEED_SYSTEMD" != "1" ]; then
    echo "For unattended auto-sync (RPi etc.):  $0 --systemd"
fi
