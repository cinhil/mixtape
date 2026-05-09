"""Custom Textual widgets — small UX tweaks shared across screens.

Usage in screens:

    from ..widgets import Checkbox

instead of the stock ``textual.widgets.Checkbox``.
"""
from __future__ import annotations

from textual.widgets import Checkbox as _Checkbox


class Checkbox(_Checkbox):
    """A clearer checkbox: ``[ ]`` when off, ``[✓]`` when on, with a strong
    colour contrast so the toggle state is obvious at a glance.

    The stock Textual checkbox shows ``▐X▌`` and relies on a subtle colour
    change to convey state, which doesn't read as a toggle on most themes.
    We swap the inner glyph based on value, give the ``[ ]`` frame a panel
    background to set it apart from labels, and tint the whole control
    when toggled on.
    """

    BUTTON_LEFT = "["
    BUTTON_RIGHT = "]"
    BUTTON_INNER = " "  # default; swapped to "✓" by _sync_inner below

    DEFAULT_CSS = """
    Checkbox {
        background: transparent;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    Checkbox > .toggle--button {
        text-style: bold;
        color: $text-muted;
        background: $panel;
    }
    Checkbox.-on > .toggle--button {
        color: $success;
        background: $success 20%;
    }
    Checkbox > .toggle--label {
        padding-left: 1;
        color: $text-muted;
    }
    Checkbox.-on > .toggle--label {
        color: $text;
        text-style: bold;
    }
    Checkbox:hover > .toggle--button {
        background: $primary 30%;
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
