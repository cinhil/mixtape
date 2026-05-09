"""Custom Textual widgets — small UX tweaks shared across screens.

Usage in screens:

    from ..widgets import Checkbox

instead of the stock ``textual.widgets.Checkbox``.
"""
from __future__ import annotations

from textual.widgets import Checkbox as _Checkbox


class Checkbox(_Checkbox):
    """A clearer checkbox: ``[ ]`` when off, ``[✓]`` when on.

    The stock Textual checkbox shows ``▐X▌`` and relies on a colour change to
    convey state, which is hard to read at a glance — especially on dark
    themes. We swap the inner character based on the value, and use plain
    bracket characters as the frame.
    """

    BUTTON_LEFT = "["
    BUTTON_RIGHT = "]"
    BUTTON_INNER = " "  # default; swapped to "✓" by the watcher below

    DEFAULT_CSS = """
    Checkbox {
        background: transparent;
    }
    Checkbox > .toggle--button {
        text-style: bold;
        color: $success;
        background: transparent;
    }
    Checkbox.-on > .toggle--button {
        color: $success;
        background: transparent;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sync_inner()

    def watch_value(self) -> None:
        # Textual ToggleButton's reactive `value` triggers this when toggled.
        self._sync_inner()

    def _sync_inner(self) -> None:
        self.BUTTON_INNER = "✓" if self.value else " "
        self.refresh()
