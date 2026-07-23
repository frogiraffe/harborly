from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sea_mile.geo import great_circle_nmi, validate_coordinate
from sea_mile.sources.reference import parse_unlocode_coordinates, parse_wpi_dms
from sea_mile.text import canonical_key, normalize_display_text

_ALLOWED_KEY_CHARACTERS = set("abcdefghijklmnopqrstuvwxyz0123456789 ")
_HALF_CIRCUMFERENCE_NMI = 10810

latitudes = st.floats(
    min_value=-90, max_value=90, allow_nan=False, allow_infinity=False
)
longitudes = st.floats(
    min_value=-180, max_value=180, allow_nan=False, allow_infinity=False
)


@given(st.text())
def test_canonical_key_is_idempotent_and_restricted(text: str) -> None:
    key = canonical_key(text)
    assert canonical_key(key) == key
    assert set(key) <= _ALLOWED_KEY_CHARACTERS
    assert key == key.strip()
    assert "  " not in key


@given(st.text())
def test_normalize_display_text_never_crashes(text: str) -> None:
    result = normalize_display_text(text)
    assert isinstance(result, str)
    assert result == result.strip()


@given(latitudes, longitudes, latitudes, longitudes)
def test_great_circle_is_symmetric_and_bounded(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> None:
    forward = great_circle_nmi(lat1, lon1, lat2, lon2)
    backward = great_circle_nmi(lat2, lon2, lat1, lon1)
    assert math.isfinite(forward)
    assert 0 <= forward <= _HALF_CIRCUMFERENCE_NMI
    assert forward == pytest.approx(backward)


@given(latitudes, longitudes)
def test_validate_coordinate_accepts_in_range(lat: float, lon: float) -> None:
    check = validate_coordinate(lat, lon)
    if lat == 0.0 and lon == 0.0:
        assert not check.is_valid
    else:
        assert check.is_valid


@given(
    st.integers(min_value=0, max_value=179),
    st.integers(min_value=0, max_value=59),
    st.integers(min_value=0, max_value=59),
    st.sampled_from("NSEW"),
)
def test_parse_wpi_dms_stays_in_bounds(
    degrees: int, minutes: int, seconds: int, direction: str
) -> None:
    text = f"{degrees}°{minutes:02d}'{seconds:02d}\"{direction}"
    result = parse_wpi_dms(text)
    if result is not None:
        limit = 90 if direction in "NS" else 180
        assert -limit <= result <= limit


@given(st.text())
def test_parse_wpi_dms_never_raises(text: str) -> None:
    parse_wpi_dms(text)


@given(st.text())
def test_parse_unlocode_never_raises(text: str) -> None:
    result = parse_unlocode_coordinates(text)
    if result is not None:
        latitude, longitude = result
        assert -90 <= latitude <= 90
        assert -180 <= longitude <= 180
