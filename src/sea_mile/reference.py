"""Parsers for authoritative port-reference coordinate formats."""

import re

_WPI_DMS = re.compile(
    r"^\s*(?P<degrees>\d{1,3})°(?P<minutes>\d{1,2})'"
    r"(?P<seconds>\d{1,2}(?:\.\d+)?)\"(?P<direction>[NSEW])\s*$"
)
_UNLOCODE_COORDINATES = re.compile(
    r"^\s*(?P<lat_degrees>\d{2})(?P<lat_minutes>\d{2})(?P<lat_direction>[NS])"
    r"\s+(?P<lon_degrees>\d{3})(?P<lon_minutes>\d{2})(?P<lon_direction>[EW])\s*$"
)


def parse_wpi_dms(value: object) -> float | None:
    """Parse a WPI degree-minute-second coordinate into decimal degrees."""

    if value is None:
        return None
    match = _WPI_DMS.match(str(value))
    if not match:
        return None
    degrees = float(match.group("degrees"))
    minutes = float(match.group("minutes"))
    seconds = float(match.group("seconds"))
    result = degrees + minutes / 60 + seconds / 3600
    direction = match.group("direction")
    if result > (90 if direction in {"N", "S"} else 180):
        return None
    if direction in {"S", "W"}:
        result *= -1
    return result


def parse_unlocode_coordinates(value: object) -> tuple[float, float] | None:
    """Parse a UN/LOCODE DDMM[N/S] DDDMM[E/W] coordinate pair."""

    if value is None:
        return None
    match = _UNLOCODE_COORDINATES.match(str(value))
    if not match:
        return None
    lat_minutes = float(match.group("lat_minutes"))
    lon_minutes = float(match.group("lon_minutes"))
    latitude = float(match.group("lat_degrees")) + lat_minutes / 60
    longitude = float(match.group("lon_degrees")) + lon_minutes / 60
    if latitude > 90 or longitude > 180:
        return None
    if match.group("lat_direction") == "S":
        latitude *= -1
    if match.group("lon_direction") == "W":
        longitude *= -1
    return latitude, longitude
