"""Braille world map renderer for terminal port visualization.

Renders coastlines and port markers onto a :class:`BrailleCanvas` using
equirectangular projection.  Coastlines come from embedded Natural Earth
110m data; ports are projected from ``PortGroup`` coordinates using the
project's :class:`~sea_mile.coordinates.LatLon` contract.
"""

from __future__ import annotations

from collections.abc import Sequence

from sea_mile.coordinates import LatLon
from sea_mile.ports import PortGroup
from sea_mile.tui.braille import BrailleCanvas
from sea_mile.tui.coastlines import load_coastlines

# ANSI escape codes for map layers.
_ANSI_RESET = "\033[0m"
_ANSI_DIM_GRAY = "\033[90m"
_ANSI_DIM_CYAN = "\033[36m"
_ANSI_BRIGHT_RED = "\033[91m"
_ANSI_BOLD = "\033[1m"


def _geo_to_pixel(
    latlon: LatLon,
    canvas_width: int,
    canvas_height: int,
) -> tuple[int, int]:
    """Project a WGS84 coordinate to canvas pixel coordinates.

    Uses equirectangular projection with an inverted Y-axis (terminal
    convention: row 0 is the top, i.e. north pole).
    """
    x = int((latlon.longitude + 180.0) / 360.0 * canvas_width)
    y = int((90.0 - latlon.latitude) / 180.0 * canvas_height)
    # Clamp to canvas bounds.
    x = max(0, min(x, canvas_width - 1))
    y = max(0, min(y, canvas_height - 1))
    return x, y


def _bresenham(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Return all integer pixels on the line from (x0,y0) to (x1,y1)."""
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return points


class BrailleWorldMap:
    """High-resolution braille world map with coastline and port rendering.

    Parameters
    ----------
    width:
        Terminal character width available for the map.
    height:
        Terminal character height available for the map.
    """

    def __init__(self, width: int, height: int) -> None:
        if width < 1 or height < 1:
            raise ValueError("map dimensions must be positive")
        self._char_width = width
        self._char_height = height
        # Pixel dimensions: 2 px per column, 4 px per row.
        self._pixel_width = width * 2
        self._pixel_height = height * 4
        self._canvas = BrailleCanvas(self._pixel_width, self._pixel_height)

    @property
    def char_width(self) -> int:
        return self._char_width

    @property
    def char_height(self) -> int:
        return self._char_height

    def draw_coastlines(self) -> None:
        """Rasterize the embedded NE 110m coastlines onto the canvas."""
        for segment in load_coastlines():
            if len(segment) < 2:
                continue
            prev = _geo_to_pixel(
                LatLon(latitude=segment[0][1], longitude=segment[0][0]),
                self._pixel_width,
                self._pixel_height,
            )
            for coord in segment[1:]:
                cur = _geo_to_pixel(
                    LatLon(latitude=coord[1], longitude=coord[0]),
                    self._pixel_width,
                    self._pixel_height,
                )
                for px, py in _bresenham(prev[0], prev[1], cur[0], cur[1]):
                    self._canvas.set_pixel(px, py)
                prev = cur

    def draw_ports(
        self,
        groups: Sequence[PortGroup],
        *,
        selected: int | None = None,
    ) -> None:
        """Plot port coordinates as braille dots.

        All ports are drawn in dim cyan.  The *selected* port (if any) is
        drawn in bright red with a cross-hair pattern for visibility.
        """
        for idx, group in enumerate(groups):
            if group.latitude is None or group.longitude is None:
                continue
            if group.coordinate_conflict:
                continue
            x, y = _geo_to_pixel(
                LatLon(latitude=group.latitude, longitude=group.longitude),
                self._pixel_width,
                self._pixel_height,
            )
            self._canvas.set_pixel(x, y)
            if idx == selected:
                # Draw a small cross-hair around the selected port.
                for offset in (-1, 0, 1):
                    self._canvas.set_pixel(x + offset, y)
                    self._canvas.set_pixel(x, y + offset)

    def clear(self) -> None:
        """Clear the canvas for re-rendering."""
        self._canvas.clear()

    def render(
        self,
        groups: Sequence[PortGroup],
        *,
        selected: int | None = None,
    ) -> str:
        """Render the full map: coastlines + ports + selection highlight.

        Returns a string of newline-separated lines, each containing ANSI-
        colored braille characters ready for terminal display.
        """
        self.clear()
        self.draw_coastlines()
        self.draw_ports(groups, selected=selected)

        raw = self._canvas.render()
        lines = raw.split("\n")

        # Build a pixel-level lookup for color assignment.
        colored_lines: list[str] = []
        for row_idx, line in enumerate(lines):
            parts: list[str] = []
            for col_idx, ch in enumerate(line):
                if ch == "\u2800":
                    # Empty cell — no dots set.
                    parts.append(ch)
                    continue
                # Determine dominant color: check if any dot in this cell
                # belongs to a selected port.
                color = _ANSI_DIM_GRAY  # default: coastline color
                px_center = col_idx * 2 + 1
                py_center = row_idx * 4 + 2
                for idx, group in enumerate(groups):
                    if group.latitude is None or group.longitude is None:
                        continue
                    if group.coordinate_conflict:
                        continue
                    gx, gy = _geo_to_pixel(
                        LatLon(
                            latitude=group.latitude,
                            longitude=group.longitude,
                        ),
                        self._pixel_width,
                        self._pixel_height,
                    )
                    # Check if this cell contains the port dot.
                    if (gx // 2 == col_idx and gy // 4 == row_idx) or (
                        idx == selected
                        and abs(gx - px_center) <= 3
                        and abs(gy - py_center) <= 5
                    ):
                        if idx == selected:
                            color = _ANSI_BRIGHT_RED + _ANSI_BOLD
                        else:
                            color = _ANSI_DIM_CYAN
                        break
                parts.append(f"{color}{ch}{_ANSI_RESET}")
            colored_lines.append("".join(parts))
        return "\n".join(colored_lines)
