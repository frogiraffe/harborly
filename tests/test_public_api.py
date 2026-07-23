from __future__ import annotations

import warnings

import pytest

import sea_mile

_CORE = {
    "AmbiguousPortError",
    "BatchMatchResult",
    "ConfidenceTier",
    "MatchReason",
    "MatchStatus",
    "Port",
    "PortCoordinateError",
    "PortGroup",
    "PortNotFoundError",
    "PortRegistry",
    "RegistryDataError",
    "RouteQualityFlag",
    "RoutingError",
    "SeaMileError",
    "SeaRoute",
    "SeaRouter",
    "SourceDataError",
}

_DEPRECATED = {
    "CoordinateCheck",
    "ExactMatchDecision",
    "MatchCandidate",
    "NearbyPortGroup",
    "NearbyPortResult",
    "PortSearchResult",
    "assign_canonical_ids",
    "build_reference_registry",
    "canonical_key",
    "decide_exact_match",
    "download_reference_data",
    "great_circle_nmi",
    "normalize_display_text",
    "parse_unlocode_coordinates",
    "parse_wpi_dms",
    "validate_coordinate",
}


def test_all_is_exactly_the_core_surface() -> None:
    assert set(sea_mile.__all__) == _CORE


def test_core_names_resolve_without_a_deprecation_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        for name in sea_mile.__all__:
            assert getattr(sea_mile, name) is not None


@pytest.mark.parametrize("name", sorted(_DEPRECATED))
def test_deprecated_name_warns_but_still_resolves(name: str) -> None:
    with pytest.warns(DeprecationWarning, match=name):
        value = getattr(sea_mile, name)
    assert value is not None


@pytest.mark.parametrize("name", sorted(_DEPRECATED))
def test_deprecated_name_is_not_advertised(name: str) -> None:
    assert name not in sea_mile.__all__


def test_deprecated_names_import_cleanly_from_their_modules() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        from sea_mile.normalization import canonical_key
        from sea_mile.quality import great_circle_nmi

    assert canonical_key("Mersin")
    assert great_circle_nmi(0.0, 0.0, 0.0, 1.0) > 0


def test_unknown_attribute_still_raises() -> None:
    with pytest.raises(AttributeError):
        _ = sea_mile.does_not_exist
