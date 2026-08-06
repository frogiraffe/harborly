"""Type-safe coordinate representations at spatial library boundaries."""

from __future__ import annotations

from typing import NamedTuple


class LatLon(NamedTuple):
    """A WGS84 coordinate in latitude, longitude order."""

    latitude: float
    longitude: float

    def to_lon_lat(self) -> LonLat:
        return LonLat(longitude=self.longitude, latitude=self.latitude)


class LonLat(NamedTuple):
    """A WGS84 coordinate in longitude, latitude (X/Y) order."""

    longitude: float
    latitude: float

    def as_list(self) -> list[float]:
        return [self.longitude, self.latitude]
