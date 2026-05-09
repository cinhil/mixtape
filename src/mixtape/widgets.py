"""Custom Textual widgets — small UX tweaks shared across screens.

Usage in screens:

    from ..widgets import Checkbox

instead of the stock ``textual.widgets.Checkbox``.
"""
from __future__ import annotations

from textual.widgets import Checkbox as _Checkbox


class Checkbox(_Checkbox):
    """A clearer checkbox: ``[ ]`` when off, ``[✓]`` when on.

    The stock Textual checkbox shows ``▐X▌`` and relies on a colour change
    to convey state, which doesn't read as a toggle. We swap the inner
    glyph based on value.
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
        self._sync_inner()

    def _sync_inner(self) -> None:
        self.BUTTON_INNER = "✓" if self.value else " "
        self.refresh()
