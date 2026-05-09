"""Mixtape entry-point dispatcher.

Modes
-----
  mixtape                    → daemon-driven TUI (default; auto-starts daemon)
  mixtape --daemon           → run the daemon in foreground (systemd / launchd)
  mixtape --desktop          → PySide6 GUI (Windows / macOS; Linux desktop)
  mixtape --set-cookies      → read cookies from stdin (SSH-friendly, headless)
  mixtape --headless         → deprecated alias for --daemon (kept for systemd
                                units that haven't been re-installed yet)

The legacy in-process TUI (`MixtapeApp`), pystray tray, dual-process PID
files and console-detachment ceremony have all been retired. Sync, USB
watching, bgutil, and cookie/update orchestration all live inside the
daemon (mixtape.services.Application); UIs are thin clients."""
from __future__ import annotations


def main() -> None:
    import sys
    argv = sys.argv[1:]
    if "--set-cookies" in argv:
        from .cli import set_cookies_from_stdin
        sys.exit(set_cookies_from_stdin())
    if "--daemon" in argv or "--headless" in argv or "-H" in argv:
        from .daemon.main import main as daemon_main
        sys.exit(daemon_main(
            [a for a in argv if a not in {"--daemon", "--headless", "-H"}]
        ))
    if "--desktop" in argv:
        from .desktop import run_desktop
        sys.exit(run_desktop())
    # Default: thin TUI. Talks to the daemon (auto-spawning if needed).
    from .tui import run_tui
    sys.exit(run_tui())


if __name__ == "__main__":
    main()
