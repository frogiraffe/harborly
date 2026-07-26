"""Optional Plotext rendering for terminal port maps."""

from __future__ import annotations

from collections.abc import Sequence

import plotext

from sea_mile.coordinates import LonLat
from sea_mile.ports import PortGroup


def _group_lon_lat(group: PortGroup) -> LonLat | None:
    if group.coordinate_conflict or group.latitude is None or group.longitude is None:
        return None
    return LonLat(longitude=group.longitude, latitude=group.latitude)


def render_port_map(
    groups: Sequence[PortGroup],
    *,
    selected: int,
    width: int = 48,
    height: int = 14,
) -> str:
    """Render result coordinates and the selected port on a world extent."""

    points = [
        (index, point)
        for index, group in enumerate(groups)
        if (point := _group_lon_lat(group)) is not None
    ]
    plotext.clf()
    plotext.plotsize(width, height)
    plotext.xlim(-180, 180)
    plotext.ylim(-90, 90)
    plotext.xlabel("longitude")
    plotext.ylabel("latitude")
    plotext.title("Search result coordinates")
    if points:
        plotext.scatter(
            [point.longitude for _, point in points],
            [point.latitude for _, point in points],
            marker="dot",
            color="cyan",
        )
    selected_point = next(
        (point for index, point in points if index == selected),
        None,
    )
    if selected_point is not None:
        plotext.scatter(
            [selected_point.longitude],
            [selected_point.latitude],
            marker="x",
            color="yellow",
        )
    return str(plotext.build())
