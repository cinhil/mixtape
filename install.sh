#!/usr/bin/env bash
#
# mixtape — one-shot Linux / macOS / Raspberry Pi installer.
#
# Run as a one-liner from any terminal (no clone needed):
#
#   curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash
#
# Flags:
#   --systemd     install a systemd --user service that runs the daemon at
#                 boot (Linux only).
#   --launchd     install a macOS LaunchAgent that runs the daemon at login.
#   --desktop     also install the optional PySide6 GUI extras (large; only
#                 useful on a desktop with a display).
#   --dev         follow the 'main' branch instead of the latest release tag.
#   --ref=X       pin to a specific tag, branch, or commit.
#
# Default behaviour: install / update to the latest GitHub Release. If no
# release exists yet, falls back to 'main'.
#
# Override install location with: MIXTAPE_DIR=/some/path bash <(curl …)
# Idempotent: safe to re-run (it pulls / checks out the target ref). On
# update, restarts the running daemon if the systemd unit is loaded.

set -e

REPO_URL="https://github.com/cinhil/mixtape.git"
REPO_API="https://api.github.com/repos/cinhil/mixtape/releases/latest"
DEFAULT_INSTALL="${MIXTAPE_DIR:-$HOME/.local/share/mixtape-app}"

NEED_SYSTEMD=0
NEED_LAUNCHD=0
NEED_DESKTOP=0
USE_DEV=0
EXPLICIT_REF=""
for arg in "$@"; do
    case "$arg" in
        --systemd) NEED_SYSTEMD=1 ;;
        --launchd) NEED_LAUNCHD=1 ;;
        --desktop) NEED_DESKTOP=1 ;;
        --dev)     USE_DEV=1 ;;
        --ref=*)   EXPLICIT_REF="${arg#*=}" ;;
        --help|-h)
            sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
    esac
done

# Detect platform — drives apt-vs-brew + service-installer choice.
case "$(uname -s)" in
    Linux*)  PLATFORM="linux" ;;
    Darwin*) PLATFORM="macos" ;;
    *)       PLATFORM="unknown" ;;
esac

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

# 1. system packages ----------------------------------------------------------
cyan ""
cyan "=== Step 1/6 — system packages ==="
if [ "$PLATFORM" = "linux" ]; then
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
elif [ "$PLATFORM" = "macos" ]; then
    if ! command -v brew >/dev/null 2>&1; then
        fail "Homebrew is required on macOS. Install it from https://brew.sh"
    fi
    need_brew=()
    for pkg in ffmpeg git; do
        if brew list --formula "$pkg" >/dev/null 2>&1; then
            ok "$pkg already installed"
        else
            need_brew+=("$pkg")
        fi
    done
    if [ "${#need_brew[@]}" -gt 0 ]; then
        step "brew install ${need_brew[*]}"
        brew install "${need_brew[@]}"
    fi
else
    fail "unsupported platform: $(uname -s)"
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
if [ "$NEED_DESKTOP" = "1" ]; then
    step "uv sync --extra desktop (PySide6 + qasync — heavyweight) …"
    uv sync --extra desktop
else
    step "uv sync …"
    uv sync
fi
ok "Python deps up to date"
step "Setting up / refreshing bgutil companion …"
./setup-bgutil.sh
ok "bgutil companion ready"

# 6. background service (optional) -------------------------------------------
cyan ""
cyan "=== Step 6/6 — background service (optional) ==="
if [ "$PLATFORM" = "linux" ] && [ "$NEED_SYSTEMD" = "1" ]; then
    target_dir="$HOME/.config/systemd/user"
    mkdir -p "$target_dir"
    sed "s|^WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|" mixtape.service \
        > "$target_dir/mixtape.service"
    systemctl --user daemon-reload
    if systemctl --user is-active --quiet mixtape.service; then
        # Already running — restart so it picks up the new code.
        systemctl --user restart mixtape.service
        ok "mixtape.service restarted"
    else
        systemctl --user enable --now mixtape.service
        ok "mixtape.service installed — see  journalctl --user -u mixtape -f"
    fi
elif [ "$PLATFORM" = "macos" ] && [ "$NEED_LAUNCHD" = "1" ]; then
    plist="$HOME/Library/LaunchAgents/com.cinhil.mixtape.daemon.plist"
    label="com.cinhil.mixtape.daemon"
    log_path="$HOME/Library/Logs/mixtape-daemon.log"
    mkdir -p "$(dirname "$plist")" "$(dirname "$log_path")"
    daemon_exe="$INSTALL_DIR/.venv/bin/mixtape-daemon"
    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key><array><string>${daemon_exe}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>WorkingDirectory</key><string>${INSTALL_DIR}</string>
  <key>StandardOutPath</key><string>${log_path}</string>
  <key>StandardErrorPath</key><string>${log_path}</string>
</dict></plist>
PLIST
    # Modern verb (macOS 10.10+); fall back to legacy load -w.
    uid="$(id -u)"
    launchctl bootout "gui/${uid}/${label}" 2>/dev/null || true
    launchctl bootstrap "gui/${uid}" "$plist" 2>/dev/null \
        || launchctl load -w "$plist"
    ok "LaunchAgent installed — see  tail -f $log_path"
else
    step "Skipping background service install (pass --systemd on Linux or --launchd on macOS)"
fi

# 7. restart any running daemon so it picks up the new code -------------------
if pgrep -f "mixtape.daemon.main\|mixtape-daemon" >/dev/null 2>&1; then
    cyan ""
    step "Asking the running daemon to restart so it picks up the new code …"
    # We don't have a /restart endpoint — telling it to /shutdown is enough;
    # systemd / launchd / the desktop UI's autostart will bring it back.
    daemon_pids=$(pgrep -f "mixtape.daemon.main\|mixtape-daemon" || true)
    for pid in $daemon_pids; do
        kill -TERM "$pid" 2>/dev/null || true
    done
fi

cyan ""
cyan "✓ All done."
echo "Project lives at: $INSTALL_DIR"
echo ""
echo "Launch options:"
echo "  TUI (default):    cd $INSTALL_DIR && ./run.sh"
echo "  Daemon (manual):  cd $INSTALL_DIR && uv run mixtape-daemon"
if [ "$NEED_DESKTOP" = "1" ]; then
    echo "  Desktop GUI:      cd $INSTALL_DIR && uv run mixtape --desktop"
fi
echo ""
if [ "$PLATFORM" = "linux" ] && [ "$NEED_SYSTEMD" != "1" ]; then
    echo "Auto-start at boot:   $0 --systemd"
fi
if [ "$PLATFORM" = "macos" ] && [ "$NEED_LAUNCHD" != "1" ]; then
    echo "Auto-start at login:  $0 --launchd"
fi
