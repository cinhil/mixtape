"""Custom Textual widgets — small UX tweaks shared across screens.

Usage in screens:

    from ..widgets import Checkbox

instead of the stock ``textual.widgets.Checkbox``.
"""
from __future__ import annotations

from textual.content import Content
from textual.style import Style
from textual.widgets import Checkbox as _Checkbox


class Checkbox(_Checkbox):
    """A clearer checkbox: ``[ ]`` when off, ``[✓]`` when on, with strong
    colour contrast so the toggle state is obvious at a glance.

    The stock Textual checkbox shows ``▐X▌`` and relies on a subtle colour
    change to convey state, which doesn't read as a toggle on most themes.
    We render the bracketed frame ourselves (overriding the ``_button``
    property) so the inner glyph reflects ``self.value`` directly at every
    render — no reactive race between ``__init__`` and the first paint.
    """

    BUTTON_LEFT = "["
    BUTTON_RIGHT = "]"
    BUTTON_INNER = "✓"  # used only as a fallback; real glyph computed below

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

    @property
    def _button(self) -> Content:  # type: ignore[override]
        button_style = self.get_visual_style("toggle--button")
        # Paint the [ ] frame in the *label* color so the brackets stay
        # visible against the dialog surface — the parent class would put
        # them in button_style.background, which blends into the button
        # background we just gave it.
        label_style = self.get_visual_style("toggle--label")
        side_style = Style(
            foreground=label_style.foreground,
            background=self.background_colors[1],
        )
        inner = "✓" if self.value else " "
        return Content.assemble(
            (self.BUTTON_LEFT, side_style),
            (inner, button_style),
            (self.BUTTON_RIGHT, side_style),
        )

    def watch_value(self) -> None:
        # Force a re-render so the inner glyph flips immediately on toggle.
        self.refresh()
