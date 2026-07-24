"""Stable coordinate and distance quality rules."""

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any

_MEAN_EARTH_RADIUS_KM = 6371.0087714
_KM_PER_NMI = 1.852
_EARTH_RADIUS_NMI = _MEAN_EARTH_RADIUS_KM / _KM_PER_NMI


@dataclass(frozen=True, slots=True)
class CoordinateCheck:
    is_valid: bool
    reason: str | None = None


def validate_coordinate(latitude: Any, longitude: Any) -> CoordinateCheck:
    """Reject missing, non-numeric, out-of-range, and Null Island coordinates."""

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return CoordinateCheck(False, "coordinate is missing or non-numeric")

    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return CoordinateCheck(
            False, "coordinate is outside valid latitude/longitude bounds"
        )
    if lat == 0.0 and lon == 0.0:
        return CoordinateCheck(False, "coordinate is the (0, 0) missing-value sentinel")
    return CoordinateCheck(True)


def great_circle_nmi(
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> float:
    """Return the Haversine great-circle distance in nautical miles."""

    lat1, lon1, lat2, lon2 = map(
        radians,
        (
            origin_latitude,
            origin_longitude,
            destination_latitude,
            destination_longitude,
        ),
    )
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = (
        sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )
    # Clamp so float rounding above 1.0 for near-antipodal points cannot make
    # asin raise a math domain error.
    central_angle = 2 * asin(min(1.0, sqrt(haversine)))
    return _EARTH_RADIUS_NMI * central_angle
