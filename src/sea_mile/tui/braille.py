"""Pure-Python braille canvas for terminal pixel graphics.

Each terminal cell displays a 2x4 braille pattern (U+2800..U+28FF),
providing 8x the resolution of standard character cells.

Dot layout per cell::

    bit0  bit3
    bit1  bit4
    bit2  bit5
    bit6  bit7
"""

from __future__ import annotations

from collections.abc import Iterator

_BRAILLE_OFFSET = 0x2800

# Dot bit values indexed by (column, row) where column in {0, 1} and
# row in {0, 1, 2, 3}.
_DOT_BITS: list[list[int]] = [
    [0x01, 0x02, 0x04, 0x40],  # left column
    [0x08, 0x10, 0x20, 0x80],  # right column
]


def _char_from_dots(dots: int) -> str:
    """Convert an 8-bit dot mask to a braille Unicode character."""
    return chr(_BRAILLE_OFFSET + dots)


class BrailleCanvas:
    """A pixel-addressable canvas rendered as Unicode braille characters.

    Parameters
    ----------
    pixel_width:
        Width in pixels (each terminal column = 2 pixels).
    pixel_height:
        Height in pixels (each terminal row = 4 pixels).
    """

    def __init__(self, pixel_width: int, pixel_height: int) -> None:
        if pixel_width < 0 or pixel_height < 0:
            raise ValueError("dimensions must be non-negative")
        self._pw = pixel_width
        self._ph = pixel_height
        self._cols = (pixel_width + 1) // 2
        self._rows = (pixel_height + 1) // 4
        # One int per cell; each int holds the 8-bit dot mask.
        self._cells: list[int] = [0] * (self._cols * self._rows)

    @property
    def pixel_width(self) -> int:
        return self._pw

    @property
    def pixel_height(self) -> int:
        return self._ph

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def rows(self) -> int:
        return self._rows

    def clear(self) -> None:
        """Reset all dots to off."""
        for i in range(len(self._cells)):
            self._cells[i] = 0

    def set_pixel(self, x: int, y: int) -> None:
        """Turn on a single pixel."""
        if 0 <= x < self._pw and 0 <= y < self._ph:
            col = x // 2
            row = y // 4
            bit = _DOT_BITS[x % 2][y % 4]
            self._cells[row * self._cols + col] |= bit

    def unset_pixel(self, x: int, y: int) -> None:
        """Turn off a single pixel."""
        if 0 <= x < self._pw and 0 <= y < self._ph:
            col = x // 2
            row = y // 4
            bit = _DOT_BITS[x % 2][y % 4]
            self._cells[row * self._cols + col] &= ~bit

    def _iter_rows(self) -> Iterator[str]:
        """Yield one braille string per row."""
        for r in range(self._rows):
            start = r * self._cols
            yield "".join(
                _char_from_dots(self._cells[start + c]) for c in range(self._cols)
            )

    def render(self) -> str:
        """Return the canvas as a newline-joined braille string."""
        return "\n".join(self._iter_rows())

    def __len__(self) -> int:
        return len(self._cells)
