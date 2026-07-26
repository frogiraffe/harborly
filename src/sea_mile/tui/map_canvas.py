"""Braille world map renderer with zoom, pan, and port clustering.

Renders coastlines and port markers onto a :class:`BrailleCanvas` using
equirectangular projection.  Supports viewport transformation (zoom/pan)
and aggregates nearby ports into clusters at low zoom levels.

Coastlines come from embedded Natural Earth 110m data; ports are projected
from ``PortGroup`` coordinates using the project's
:class:`~sea_mile.coordinates.LatLon` contract.
"""

from __future__ import annotations

from collections.abc import Sequence

from sea_mile.coordinates import LatLon
from sea_mile.ports import PortGroup
from sea_mile.tui.braille import BrailleCanvas
from sea_mile.tui.coastlines import load_coastlines

_ANSI_RESET = "\033[0m"
_ANSI_DIM_GRAY = "\033[90m"
_ANSI_DIM_CYAN = "\033[36m"
_ANSI_BRIGHT_RED = "\033[91m"
_ANSI_BOLD = "\033[1m"

_CLUSTER_RADIUS_PX = 4


def _geo_to_pixel(
    latlon: LatLon,
    canvas_width: int,
    canvas_height: int,
    *,
    zoom: float = 1.0,
    center_lat: float = 0.0,
    center_lon: float = 0.0,
) -> tuple[int, int]:
    """Project a WGS84 coordinate to canvas pixel coordinates.

    Supports viewport transformation via *zoom* and center coordinates.
    Uses equirectangular projection with an inverted Y-axis.
    """
    lon_offset = latlon.longitude - center_lon
    if lon_offset > 180.0:
        lon_offset -= 360.0
    elif lon_offset < -180.0:
        lon_offset += 360.0
    lat_offset = latlon.latitude - center_lat

    visible_lon = 360.0 / zoom
    visible_lat = 180.0 / zoom

    x = int((lon_offset + visible_lon / 2.0) / visible_lon * canvas_width)
    y = int((visible_lat / 2.0 - lat_offset) / visible_lat * canvas_height)

    x = max(0, min(x, canvas_width - 1))
    y = max(0, min(y, canvas_height - 1))
    return x, y


def _in_viewport(
    lat: float,
    lon: float,
    *,
    zoom: float,
    center_lat: float,
    center_lon: float,
) -> bool:
    """Check whether a coordinate falls inside the current viewport."""
    visible_lon = 360.0 / zoom
    visible_lat = 180.0 / zoom
    lon_diff = abs(lon - center_lon)
    if lon_diff > 180.0:
        lon_diff = 360.0 - lon_diff
    return (
        lon_diff <= visible_lon / 2.0 + 1.0
        and abs(lat - center_lat) <= visible_lat / 2.0 + 1.0
    )


def _bresenham(
    x0: int, y0: int, x1: int, y1: int, *, step: int = 1
) -> list[tuple[int, int]]:
    """Return pixels on the line from (x0,y0) to (x1,y1).

    *step* skips intermediate pixels to thin long lines at low zoom.
    """
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    count = 0
    while True:
        if count % step == 0:
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
        count += 1
    return points


def _port_pixel(
    group: PortGroup,
    canvas_width: int,
    canvas_height: int,
    *,
    zoom: float,
    center_lat: float,
    center_lon: float,
) -> tuple[int, int] | None:
    """Return pixel coordinates for a port, or None if unavailable."""
    if group.latitude is None or group.longitude is None:
        return None
    if group.coordinate_conflict:
        return None
    return _geo_to_pixel(
        LatLon(latitude=group.latitude, longitude=group.longitude),
        canvas_width,
        canvas_height,
        zoom=zoom,
        center_lat=center_lat,
        center_lon=center_lon,
    )


class _Cluster:
    """A group of nearby ports aggregated into a single visual marker."""

    __slots__ = ("px", "py", "indices", "selected_idx")

    def __init__(self, px: int, py: int) -> None:
        self.px = px
        self.py = py
        self.indices: list[int] = []
        self.selected_idx: int | None = None


def _cluster_ports(
    groups: Sequence[PortGroup],
    canvas_width: int,
    canvas_height: int,
    *,
    zoom: float,
    center_lat: float,
    center_lon: float,
) -> list[_Cluster]:
    """Aggregate nearby ports into clusters based on pixel proximity."""
    clusters: list[_Cluster] = []
    for idx, group in enumerate(groups):
        pt = _port_pixel(
            group,
            canvas_width,
            canvas_height,
            zoom=zoom,
            center_lat=center_lat,
            center_lon=center_lon,
        )
        if pt is None:
            continue
        px, py = pt
        merged = False
        for cl in clusters:
            if (
                abs(px - cl.px) <= _CLUSTER_RADIUS_PX
                and abs(py - cl.py) <= _CLUSTER_RADIUS_PX
            ):
                cl.indices.append(idx)
                merged = True
                break
        if not merged:
            c = _Cluster(px, py)
            c.indices.append(idx)
            clusters.append(c)
    return clusters


class BrailleWorldMap:
    """High-resolution braille world map with zoom, pan, and clustering.

    Parameters
    ----------
    width:
        Terminal character width available for the map.
    height:
        Terminal character height available for the map.
    zoom:
        Zoom factor (1.0 = full world, higher = zoomed in).
    center_lat:
        Viewport center latitude in degrees.
    center_lon:
        Viewport center longitude in degrees.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        zoom: float = 1.0,
        center_lat: float = 0.0,
        center_lon: float = 0.0,
    ) -> None:
        if width < 1 or height < 1:
            raise ValueError("map dimensions must be positive")
        if zoom < 1.0:
            zoom = 1.0
        self._char_width = width
        self._char_height = height
        self._zoom = zoom
        self._center_lat = center_lat
        self._center_lon = center_lon
        self._pixel_width = width * 2
        self._pixel_height = height * 4
        self._canvas = BrailleCanvas(self._pixel_width, self._pixel_height)

    @property
    def char_width(self) -> int:
        return self._char_width

    @property
    def char_height(self) -> int:
        return self._char_height

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def center_lat(self) -> float:
        return self._center_lat

    @property
    def center_lon(self) -> float:
        return self._center_lon

    def draw_coastlines(self) -> None:
        """Rasterize visible NE 110m coastlines onto the canvas."""
        for segment in load_coastlines():
            if len(segment) < 2:
                continue
            # Skip segments entirely outside the viewport.
            lats = [c[1] for c in segment]
            lons = [c[0] for c in segment]
            if not (
                _in_viewport(
                    min(lats),
                    min(lons),
                    zoom=self._zoom,
                    center_lat=self._center_lat,
                    center_lon=self._center_lon,
                )
                or _in_viewport(
                    max(lats),
                    max(lons),
                    zoom=self._zoom,
                    center_lat=self._center_lat,
                    center_lon=self._center_lon,
                )
                or _in_viewport(
                    min(lats),
                    max(lons),
                    zoom=self._zoom,
                    center_lat=self._center_lat,
                    center_lon=self._center_lon,
                )
                or _in_viewport(
                    max(lats),
                    min(lons),
                    zoom=self._zoom,
                    center_lat=self._center_lat,
                    center_lon=self._center_lon,
                )
            ):
                # Quick reject: if no bounding-box corner is in viewport,
                # check if viewport is fully inside the segment's bbox.
                visible_lon = 360.0 / self._zoom
                visible_lat = 180.0 / self._zoom
                if not (
                    min(lons) <= self._center_lon + visible_lon / 2
                    and max(lons) >= self._center_lon - visible_lon / 2
                    and min(lats) <= self._center_lat + visible_lat / 2
                    and max(lats) >= self._center_lat - visible_lat / 2
                ):
                    continue

            prev = _geo_to_pixel(
                LatLon(latitude=segment[0][1], longitude=segment[0][0]),
                self._pixel_width,
                self._pixel_height,
                zoom=self._zoom,
                center_lat=self._center_lat,
                center_lon=self._center_lon,
            )
            for coord in segment[1:]:
                cur = _geo_to_pixel(
                    LatLon(latitude=coord[1], longitude=coord[0]),
                    self._pixel_width,
                    self._pixel_height,
                    zoom=self._zoom,
                    center_lat=self._center_lat,
                    center_lon=self._center_lon,
                )
                dist = max(abs(cur[0] - prev[0]), abs(cur[1] - prev[1]))
                # Thin long segments at low zoom to avoid solid lines.
                step = max(1, dist // 12)
                for px, py in _bresenham(prev[0], prev[1], cur[0], cur[1], step=step):
                    self._canvas.set_pixel(px, py)
                prev = cur

    def draw_ports(
        self,
        groups: Sequence[PortGroup],
        *,
        selected: int | None = None,
    ) -> None:
        """Plot port coordinates as braille dots with clustering.

        At low zoom levels, nearby ports are merged into clusters showing
        a count badge.  The selected port is always drawn in bright red.
        """
        clusters = _cluster_ports(
            groups,
            self._pixel_width,
            self._pixel_height,
            zoom=self._zoom,
            center_lat=self._center_lat,
            center_lon=self._center_lon,
        )

        # Mark which cluster contains the selected port.
        if selected is not None:
            for cl in clusters:
                if selected in cl.indices:
                    cl.selected_idx = selected
                    break

        for cl in clusters:
            is_selected = cl.selected_idx is not None
            count = len(cl.indices)
            px, py = cl.px, cl.py

            if count == 1 and not is_selected:
                # Single non-selected port: one dot.
                self._canvas.set_pixel(px, py)
            elif count == 1 and is_selected:
                # Selected port: cross-hair.
                for ox in (-1, 0, 1):
                    self._canvas.set_pixel(px + ox, py)
                    self._canvas.set_pixel(px, py + ox)
            else:
                # Cluster: 2x2 block for visibility.
                for ox in (0, 1):
                    for oy in (0, 1):
                        self._canvas.set_pixel(px + ox, py + oy)

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

        Returns a string of ANSI-colored braille characters.
        """
        self.clear()
        self.draw_coastlines()
        self.draw_ports(groups, selected=selected)

        raw = self._canvas.render()
        lines = raw.split("\n")

        # Pre-compute port-to-cell mapping for O(1) color lookup.
        port_cells: dict[tuple[int, int], bool] = {}  # (col, row) -> is_selected
        clusters = _cluster_ports(
            groups,
            self._pixel_width,
            self._pixel_height,
            zoom=self._zoom,
            center_lat=self._center_lat,
            center_lon=self._center_lon,
        )
        for cl in clusters:
            is_sel = cl.selected_idx is not None
            col = cl.px // 2
            row = cl.py // 4
            port_cells[(col, row)] = is_sel
            # Cluster 2x2 block covers up to 4 cells.
            if len(cl.indices) > 1:
                for dx in (0, 1):
                    for dy in (0, 1):
                        port_cells[(col + dx, row + dy)] = is_sel

        colored_lines: list[str] = []
        for row_idx, line in enumerate(lines):
            parts: list[str] = []
            for col_idx, ch in enumerate(line):
                if ch == "\u2800":
                    parts.append(ch)
                    continue
                lookup = port_cells.get((col_idx, row_idx))
                if lookup is True:
                    color = _ANSI_BRIGHT_RED + _ANSI_BOLD
                elif lookup is False:
                    color = _ANSI_DIM_CYAN
                else:
                    color = _ANSI_DIM_GRAY
                parts.append(f"{color}{ch}{_ANSI_RESET}")
            colored_lines.append("".join(parts))
        return "\n".join(colored_lines)
