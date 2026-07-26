from __future__ import annotations

import pytest

pytest.importorskip("textual", reason="tests the optional 'tui' extra")

from sea_mile.tui.braille import BrailleCanvas  # noqa: E402


def test_canvas_dimensions() -> None:
    canvas = BrailleCanvas(10, 8)
    assert canvas.pixel_width == 10
    assert canvas.pixel_height == 8
    assert canvas.cols == 5
    assert canvas.rows == 2


def test_canvas_odd_dimensions() -> None:
    canvas = BrailleCanvas(7, 11)
    assert canvas.cols == 4  # (7+1)//2
    assert canvas.rows == 3  # (11+1)//4


def test_set_and_render_pixel() -> None:
    canvas = BrailleCanvas(4, 4)
    canvas.set_pixel(0, 0)
    rendered = canvas.render()
    assert rendered[0] != "\u2800"


def test_clear_resets_canvas() -> None:
    canvas = BrailleCanvas(4, 4)
    canvas.set_pixel(0, 0)
    canvas.clear()
    assert canvas.render() == "\u2800" * 2


def test_set_pixel_out_of_bounds_is_noop() -> None:
    canvas = BrailleCanvas(4, 4)
    canvas.set_pixel(-1, 0)
    canvas.set_pixel(100, 0)
    canvas.set_pixel(0, -1)
    canvas.set_pixel(0, 100)
    assert canvas.render() == "\u2800" * 2


def test_unset_pixel() -> None:
    canvas = BrailleCanvas(4, 4)
    canvas.set_pixel(0, 0)
    canvas.unset_pixel(0, 0)
    assert canvas.render() == "\u2800" * 2


def test_negative_dimensions_raise() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BrailleCanvas(-1, 4)
    with pytest.raises(ValueError, match="non-negative"):
        BrailleCanvas(4, -1)


def test_full_cell_is_max_braille() -> None:
    canvas = BrailleCanvas(2, 4)
    for x in range(2):
        for y in range(4):
            canvas.set_pixel(x, y)
    rendered = canvas.render()
    assert rendered == "\u28ff"


def test_len_returns_cell_count() -> None:
    canvas = BrailleCanvas(10, 8)
    assert len(canvas) == canvas.cols * canvas.rows
