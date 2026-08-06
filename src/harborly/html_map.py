"""Optional Folium rendering for sea-route HTML previews."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import folium
from branca.element import MacroElement, Template

from harborly.coordinates import LonLat
from harborly.geo import line_string_coordinates
from harborly.router import SeaRoute
from harborly.tui.coastlines import load_coastlines

_POLICY_AWARE_TILES = Template(
    """
    {% macro script(this, kwargs) %}
    if (window.location.protocol === "http:"
            || window.location.protocol === "https:") {
        {{ this._parent.get_name() }}.removeLayer(
            {{ this.coastline_layer_name }}
        );
        L.tileLayer(
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                attribution: '&copy; <a href="https://www.openstreetmap.org/'
                    + 'copyright">OpenStreetMap</a> contributors',
                maxZoom: 19
            }
        ).addTo({{ this._parent.get_name() }});
    } else {
        var offlineNotice = L.control({position: "topright"});
        offlineNotice.onAdd = function () {
            var notice = L.DomUtil.create("div", "harborly-offline-notice");
            notice.textContent = "Embedded coastline preview. Serve this file "
                + "over localhost for detailed OpenStreetMap tiles.";
            notice.style.background = "rgba(255, 255, 255, 0.92)";
            notice.style.border = "1px solid #94a3b8";
            notice.style.borderRadius = "4px";
            notice.style.color = "#0f172a";
            notice.style.font = "12px/1.35 sans-serif";
            notice.style.maxWidth = "220px";
            notice.style.padding = "6px 8px";
            return notice;
        };
        offlineNotice.addTo({{ this._parent.get_name() }});
    }
    {% endmacro %}
    """
)


class _PolicyAwareTileLayer(MacroElement):
    """Load public OSM tiles only when the page has an HTTP(S) referrer."""

    _template = _POLICY_AWARE_TILES

    def __init__(self, coastline_layer_name: str) -> None:
        super().__init__()
        self._name = "PolicyAwareOpenStreetMapTileLayer"
        self.coastline_layer_name = coastline_layer_name


def _coastline_feature_collection() -> dict[str, Any]:
    """Return the embedded Natural Earth coastlines as GeoJSON."""

    return {
        "type": "Feature",
        "properties": {
            "name": "Natural Earth 110m coastline",
            "license": "Public Domain / CC0",
        },
        "geometry": {
            "type": "MultiLineString",
            "coordinates": load_coastlines(),
        },
    }


def _route_lon_lat(route: SeaRoute) -> tuple[LonLat, ...]:
    return tuple(
        LonLat(longitude=lon, latitude=lat)
        for lon, lat in line_string_coordinates(route.geometry)
    )


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
    route_map = folium.Map(
        location=center,
        zoom_start=3,
        tiles=None,
    )
    coastline_layer = folium.GeoJson(
        _coastline_feature_collection(),
        name="Natural Earth coastline (embedded)",
        style_function=lambda _feature: {
            "color": "#64748b",
            "opacity": 0.8,
            "weight": 1,
        },
    )
    coastline_layer.add_to(route_map)
    _PolicyAwareTileLayer(coastline_layer.get_name()).add_to(route_map)
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
