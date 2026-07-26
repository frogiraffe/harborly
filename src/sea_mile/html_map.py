"""Optional Folium rendering for sea-route HTML previews."""

from __future__ import annotations

from html import escape
from pathlib import Path

import folium

from sea_mile.coordinates import LonLat
from sea_mile.router import SeaRoute


def _route_lon_lat(route: SeaRoute) -> tuple[LonLat, ...]:
    coordinates = route.geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)):
        raise ValueError("route geometry has no coordinate sequence")

    points: list[LonLat] = []
    for coordinate in coordinates:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            raise ValueError("route geometry contains an invalid coordinate")
        try:
            points.append(
                LonLat(
                    longitude=float(coordinate[0]),
                    latitude=float(coordinate[1]),
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "route geometry contains a non-numeric coordinate"
            ) from error
    if len(points) < 2:
        raise ValueError("route geometry needs at least two coordinates")
    return tuple(points)


def _route_locations(points: tuple[LonLat, ...]) -> tuple[tuple[float, float], ...]:
    """Return Leaflet locations with continuous longitudes across the dateline."""

    locations = [(points[0].latitude, points[0].longitude)]
    previous_longitude = points[0].longitude
    for point in points[1:]:
        longitude = point.longitude
        while longitude - previous_longitude > 180:
            longitude -= 360
        while longitude - previous_longitude < -180:
            longitude += 360
        locations.append((point.latitude, longitude))
        previous_longitude = longitude
    return tuple(locations)


def write_route_html(route: SeaRoute, output: Path) -> None:
    """Write one route to an interactive HTML map."""

    points = _route_lon_lat(route)
    locations = _route_locations(points)
    center = [
        sum(latitude for latitude, _ in locations) / len(locations),
        sum(longitude for _, longitude in locations) / len(locations),
    ]
    route_map = folium.Map(location=center, zoom_start=3)
    folium.PolyLine(  # type: ignore[no-untyped-call]
        locations=locations,
        color="#2563eb",
        weight=4,
        tooltip=f"{route.distance_nmi:.2f} nautical miles",
    ).add_to(route_map)
    folium.Marker(
        locations[0],
        tooltip=f"Origin: {escape(route.origin.name)}",
    ).add_to(route_map)
    folium.Marker(
        locations[-1],
        tooltip=f"Destination: {escape(route.destination.name)}",
    ).add_to(route_map)
    route_map.fit_bounds(locations)

    output.parent.mkdir(parents=True, exist_ok=True)
    route_map.save(str(output))
