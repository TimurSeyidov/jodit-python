"""SVG thumbnail icons for folders and non-image files."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from jcpy.helpers.js import node_extname

if TYPE_CHECKING:
    from jcpy.storage.base import StatEntry

type SvgGenerator = Callable[[StatEntry, int, int], str]
"""Render the SVG thumbnail of an entry for the given width and height."""

type _Rgb = tuple[int, int, int]

_COLORS: tuple[_Rgb, ...] = (
    (228, 84, 83),
    (237, 234, 67),
    (122, 223, 237),
    (228, 84, 83),
    (245, 170, 43),
    (174, 196, 70),
    (212, 110, 173),
    (241, 197, 222),
    (222, 145, 154),
    (143, 205, 190),
    (148, 16, 76),
    (146, 165, 171),
    (0, 106, 180),
    (0, 106, 180),
)


def _js_round(value: float) -> int:
    """``Math.round``: halves round towards positive infinity."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _darken(value: int, percent: int) -> float:
    """``luminateValue`` for ``percent`` below 50 (the only ones used)."""
    return value * (percent * 2 / 100)


def _luminate(color: _Rgb, percent: int) -> _Rgb:
    red, green, blue = (
        min(max(0, _js_round(_darken(value, percent))), 255) for value in color
    )
    return red, green, blue


def _hex(color: _Rgb) -> str:
    return "#" + "".join(f"{value:02x}" for value in color)


def generate_icon(
    entry: StatEntry, width: int = 100, height: int = 100
) -> str:
    """Render the default icon: a colored page labeled with the extension.

    Args:
        entry: Folder or file the icon stands for.
        width: SVG width.
        height: SVG height.

    Returns:
        SVG markup, byte-identical to jodit-nodejs ``generateIcon``.
    """
    if entry.is_directory:
        word = "folder"
    else:
        word = node_extname(entry.path)[1:].lower()
    color = _COLORS[ord(word[0]) % len(_COLORS)]
    main = _hex(color)
    dark = _hex(_luminate(color, 30))
    shadow = _hex(_luminate(color, 45))

    label_x, label_y = 13, 55
    label_width = 54 if len(word) < 5 else 70
    label_height = 22
    text_x = label_x + label_width / 2
    text_y = label_y + label_height / 2 + 2
    label = (
        ""
        if entry.is_directory
        else f"""
\t\t<g>
\t\t\t<rect x="{label_x}" y="{label_y}" width="{label_width}" \
height="{label_height}" rx="4" fill="{dark}"/>
\t\t\t<text
          x="{text_x:g}"
          y="{text_y:g}"
          dominant-baseline="middle"
          text-anchor="middle"
          fill="white"
          font-family="Arial"
          font-size="16"
      >
      \t{word}
      </text>
\t\t</g>
\t\t<path d="M64.5 56.5L80 72V82.54V82.54C79.7186 86.7384 76.2078 90 72 90\
V90H52L20.5 77L64.5 56.5Z" fill="{shadow}" fill-opacity="0.5"/>
"""
    )
    return f"""
\t<svg width="{width}" height="{height}" viewBox="0 0 100 100" \
fill="none" xmlns="http://www.w3.org/2000/svg">
\t\t<path d="M20 19C20 14.5817 23.5817 11 28 11H56L80 34.5V82C80 86.4183 \
76.4183 90 72 90H28C23.5817 90 20 86.4183 20 82V19Z" fill="{main}"/>
\t\t{label}
\t\t<path d="M79.5 34L80 36.5V42L64 33.5L60.5 31L79.5 34Z" fill="{shadow}" \
fill-opacity="0.5"/>
\t\t<path d="M56 11L80 34.5L66.063 34.1832C61.4741 34.079 57.699 30.538 \
57.3013 25.9652L56 11Z" fill="{dark}"/>
\t</svg>
"""
