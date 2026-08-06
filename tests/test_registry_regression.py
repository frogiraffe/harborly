"""Regression tests for PortRegistry public behavior.

These tests lock current behaviors before refactoring so that no
unintended changes slip through.  They exercise only the public API
surface visible to library consumers.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from harborly import (
    Port,
    PortGroup,
    PortNotFoundError,
    PortRegistry,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry() -> PortRegistry:
    return PortRegistry.bundled()


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_exact_canonical_name(registry: PortRegistry) -> None:
    results = registry.search("Mersin")
    assert len(results) >= 1
    names = [r.port.name for r in results]
    assert any("Mersin" in n or "MERSIN" in n or "mersin" in n.lower() for n in names)


def test_search_exact_unlocode(registry: PortRegistry) -> None:
    results = registry.search("TRMER")
    assert len(results) >= 1
    for r in results:
        assert r.match_method == "exact_unlocode"


def test_search_fuzzy(registry: PortRegistry) -> None:
    results = registry.search("Pireus", country_code="GR")
    assert len(results) >= 1
    # Should find Piraeus-like ports
    names_lower = [r.port.name.lower() for r in results]
    assert any("pir" in n for n in names_lower)


def test_search_country_filter(registry: PortRegistry) -> None:
    results = registry.search("Hamilton", country_code="BM")
    for r in results:
        assert r.port.country_code == "BM"


def test_search_no_result(registry: PortRegistry) -> None:
    results = registry.search("ZZZZNONEXISTENT12345")
    assert len(results) == 0


def test_search_deterministic_ordering(registry: PortRegistry) -> None:
    results_a = registry.search("Istanbul", limit=10)
    results_b = registry.search("Istanbul", limit=10)
    ids_a = [r.port.registry_id for r in results_a]
    ids_b = [r.port.registry_id for r in results_b]
    assert ids_a == ids_b


def test_search_limit(registry: PortRegistry) -> None:
    results = registry.search("Port", limit=5)
    assert len(results) <= 5


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def test_resolve_by_registry_id(registry: PortRegistry) -> None:
    # Get a known port
    port = registry.get("WPI:42230")
    assert port is not None
    assert port.registry_id == "WPI:42230"


def test_resolve_by_unlocode(registry: PortRegistry) -> None:
    port = registry.resolve("TRMER")
    assert port is not None
    assert port.country_code == "TR"


def test_resolve_unknown_raises(registry: PortRegistry) -> None:
    with pytest.raises(PortNotFoundError):
        registry.resolve("ZZNONEXISTENT999")


def test_get_by_unlocode(registry: PortRegistry) -> None:
    ports = registry.get_by_unlocode("GRPIR")
    assert len(ports) >= 1
    for p in ports:
        assert p.unlocode == "GRPIR"


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------


def test_search_grouped_returns_port_groups(registry: PortRegistry) -> None:
    groups = registry.search_grouped("Mersin", country_code="TR")
    assert len(groups) >= 1
    for g in groups:
        assert isinstance(g, PortGroup)
        assert len(g.members) >= 1


def test_group_for_unlocode(registry: PortRegistry) -> None:
    group = registry.group_for("TRMER")
    assert isinstance(group, PortGroup)
    assert group.unlocode == "TRMER"


def test_resolve_canonical(registry: PortRegistry) -> None:
    group = registry.group_for("TRMER")
    canonical = registry.resolve_canonical(group.canonical_id)
    assert canonical.canonical_id == group.canonical_id


def test_resolve_canonical_not_found(registry: PortRegistry) -> None:
    with pytest.raises(PortNotFoundError):
        registry.resolve_canonical("NONEXISTENT_CANONICAL_ID")


def test_group_source_ordering(registry: PortRegistry) -> None:
    """Sources in a group should follow provider priority."""
    group = registry.group_for("TRMER")
    if len(group.sources) > 1:
        # NGA_WPI should come before UN_LOCODE, which comes before GEONAMES
        priority = {"NGA_WPI": 0, "UN_LOCODE": 1, "GEONAMES": 2, "OPENSTREETMAP": 3}
        source_priorities = [priority.get(s, 99) for s in group.sources]
        assert source_priorities == sorted(source_priorities)


# ---------------------------------------------------------------------------
# spatial
# ---------------------------------------------------------------------------


def test_nearest(registry: PortRegistry) -> None:
    results = registry.nearest(36.8, 34.65, limit=5)
    assert len(results) >= 1
    distances = [r.distance_nmi for r in results]
    assert distances == sorted(distances)


def test_nearest_country_filter(registry: PortRegistry) -> None:
    results = registry.nearest(39.87, 26.16, country_code="TR", limit=5)
    for r in results:
        assert r.port.country_code == "TR"


def test_nearest_max_distance(registry: PortRegistry) -> None:
    results = registry.nearest(36.8, 34.65, max_distance_nmi=1.0, limit=100)
    for r in results:
        assert r.distance_nmi <= 1.0


def test_nearest_grouped(registry: PortRegistry) -> None:
    groups = registry.nearest_grouped(36.8, 34.65, limit=3)
    assert len(groups) >= 1
    for g in groups:
        assert isinstance(g.group, PortGroup)
        assert g.distance_nmi >= 0


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------


def test_port_to_dict_round_trip(registry: PortRegistry) -> None:
    port = registry.get("WPI:42230")
    d = port.to_dict()
    assert isinstance(d, dict)
    json_str = json.dumps(d)
    reloaded = json.loads(json_str)
    assert reloaded == d


def test_port_group_to_dict(registry: PortRegistry) -> None:
    group = registry.group_for("TRMER")
    d = group.to_dict()
    assert isinstance(d, dict)
    json_str = json.dumps(d)
    reloaded = json.loads(json_str)
    assert reloaded == d


def test_nearby_port_result_to_dict(registry: PortRegistry) -> None:
    results = registry.nearest(36.8, 34.65, limit=1)
    if results:
        d = results[0].to_dict()
        assert isinstance(d, dict)
        json_str = json.dumps(d)
        assert json.loads(json_str) == d


def test_port_geojson(registry: PortRegistry) -> None:
    port = registry.get("WPI:42230")
    feature = port.to_geojson_feature()
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"


# ---------------------------------------------------------------------------
# dataframe enrichment
# ---------------------------------------------------------------------------


def test_match_dataframe_no_mutation(registry: PortRegistry) -> None:
    df = pd.DataFrame({"port_name": ["Mersin", "Piraeus"]})
    original_cols = list(df.columns)
    enriched = registry.match_dataframe(df, name_column="port_name")
    # Original should not be mutated
    assert list(df.columns) == original_cols
    # Enriched should have extra columns
    assert len(enriched.columns) > len(df.columns)


# ---------------------------------------------------------------------------
# registry helpers
# ---------------------------------------------------------------------------


def test_registry_len(registry: PortRegistry) -> None:
    assert len(registry) > 0


def test_registry_contains(registry: PortRegistry) -> None:
    assert "WPI:42230" in registry


def test_registry_iter(registry: PortRegistry) -> None:
    ports = list(registry)
    assert len(ports) == len(registry)
    for p in ports[:5]:
        assert isinstance(p, Port)


def test_registry_countries(registry: PortRegistry) -> None:
    countries = registry.countries()
    assert isinstance(countries, list)
    assert len(countries) > 0
    # All should be 2-char codes
    for c in countries:
        assert isinstance(c, str)
        assert len(c) == 2


def test_registry_ports_in_country(registry: PortRegistry) -> None:
    ports = registry.ports_in_country("TR")
    assert len(ports) > 0
    for p in ports:
        assert p.country_code == "TR"


def test_registry_providers(registry: PortRegistry) -> None:
    providers = registry.providers
    assert isinstance(providers, dict)
    assert len(providers) > 0


# ---------------------------------------------------------------------------
# public API surface
# ---------------------------------------------------------------------------


def test_public_api_all_exports() -> None:
    import harborly

    for name in harborly.__all__:
        assert hasattr(harborly, name), f"{name} in __all__ but not accessible"


def test_internal_modules_not_exported() -> None:
    import harborly

    public_names = dir(harborly)
    for name in public_names:
        assert not name.startswith("_registry_"), (
            f"internal module {name} should not be in public dir()"
        )


# ---------------------------------------------------------------------------
# validation and error handling
# ---------------------------------------------------------------------------


def test_registry_validation_negative_agreement_raises() -> None:
    df = pd.DataFrame(
        {
            "registry_id": ["REG:1"],
            "provider": ["TEST"],
            "provider_id": ["1"],
            "country_code": ["XX"],
            "canonical_name": ["PORT"],
            "latitude": [10.0],
            "longitude": [20.0],
            "unlocode": [None],
            "function_code": [None],
            "source_version": ["1"],
            "coordinate_resolution": [None],
            "variant_count": [1],
            "coordinate_conflict": [False],
        }
    )
    aliases = pd.DataFrame(
        {
            "registry_id": ["REG:1"],
            "provider": ["TEST"],
            "alias": ["PORT"],
            "alias_key": ["port"],
            "alias_type": ["canonical"],
        }
    )
    with pytest.raises(ValueError, match="coordinate_agreement_nmi"):
        PortRegistry(df, aliases, coordinate_agreement_nmi=-1.0)


def test_registry_validation_incomplete_schema_raises() -> None:
    from harborly import RegistryDataError

    df = pd.DataFrame({"registry_id": ["REG:1"]})
    aliases = pd.DataFrame({"registry_id": ["REG:1"]})
    with pytest.raises(RegistryDataError, match="schema is incomplete"):
        PortRegistry(df, aliases)


def test_registry_validation_duplicate_ids_raises() -> None:
    from harborly import RegistryDataError

    df = pd.DataFrame(
        {
            "registry_id": ["REG:1", "REG:1"],
            "provider": ["TEST", "TEST"],
            "provider_id": ["1", "2"],
            "country_code": ["XX", "XX"],
            "canonical_name": ["PORT", "PORT"],
            "latitude": [10.0, 10.0],
            "longitude": [20.0, 20.0],
            "unlocode": [None, None],
            "function_code": [None, None],
            "source_version": ["1", "1"],
            "coordinate_resolution": [None, None],
            "variant_count": [1, 1],
            "coordinate_conflict": [False, False],
        }
    )
    aliases = pd.DataFrame(
        {
            "registry_id": ["REG:1", "REG:1"],
            "provider": ["TEST", "TEST"],
            "alias": ["PORT", "PORT"],
            "alias_key": ["port", "port"],
            "alias_type": ["canonical", "canonical"],
        }
    )
    with pytest.raises(RegistryDataError, match="registry_id must be unique"):
        PortRegistry(df, aliases)


def test_nearest_validation_negative_max_distance_raises(
    registry: PortRegistry,
) -> None:
    with pytest.raises(ValueError, match="max_distance_nmi"):
        registry.nearest(36.8, 34.65, max_distance_nmi=-5.0)


def test_nearest_validation_invalid_coordinate_raises(
    registry: PortRegistry,
) -> None:
    from harborly import PortCoordinateError

    with pytest.raises(PortCoordinateError):
        registry.nearest(99.0, 0.0)


def test_match_dataframe_missing_column_raises(registry: PortRegistry) -> None:
    df = pd.DataFrame({"some_other_col": ["Mersin"]})
    with pytest.raises(KeyError, match="no column 'missing_col'"):
        registry.match_dataframe(df, name_column="missing_col")


def test_search_validation_invalid_limit_raises(registry: PortRegistry) -> None:
    with pytest.raises(ValueError, match="limit must be greater than zero"):
        registry.search("Istanbul", limit=0)


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("search", ("Istanbul",)),
        ("search_grouped", ("Istanbul",)),
        ("nearest", (36.8, 34.65)),
        ("nearest_grouped", (36.8, 34.65)),
    ],
)
@pytest.mark.parametrize("limit", [True, False, 1.0, 5.5, "10", None])
def test_public_limit_apis_reject_non_integers(
    registry: PortRegistry,
    method_name: str,
    args: tuple[object, ...],
    limit: object,
) -> None:
    with pytest.raises(TypeError, match="limit must be an integer"):
        getattr(registry, method_name)(*args, limit=limit)


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("search", ("Istanbul",)),
        ("search_grouped", ("Istanbul",)),
        ("nearest", (36.8, 34.65)),
        ("nearest_grouped", (36.8, 34.65)),
    ],
)
@pytest.mark.parametrize("limit", [0, -1])
def test_public_limit_apis_reject_non_positive_integers(
    registry: PortRegistry,
    method_name: str,
    args: tuple[object, ...],
    limit: int,
) -> None:
    with pytest.raises(ValueError, match="limit must be greater than zero"):
        getattr(registry, method_name)(*args, limit=limit)


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("search", ("Istanbul",)),
        ("search_grouped", ("Istanbul",)),
        ("nearest", (36.8, 34.65)),
        ("nearest_grouped", (36.8, 34.65)),
    ],
)
@pytest.mark.parametrize("limit", [1, 10])
def test_public_limit_apis_accept_positive_integers(
    registry: PortRegistry,
    method_name: str,
    args: tuple[object, ...],
    limit: int,
) -> None:
    results = getattr(registry, method_name)(*args, limit=limit)

    assert len(results) <= limit


def test_spatial_index_initialization_is_singleton_under_concurrency(
    monkeypatch,
) -> None:
    import harborly.ports as ports_module

    original_index = ports_module.PortSpatialIndex
    registry = PortRegistry.bundled()
    workers = 50
    start = threading.Barrier(workers + 1)
    constructor_entered = threading.Event()
    release_constructor = threading.Event()
    count_lock = threading.Lock()
    constructor_count = 0

    class CountingSpatialIndex:
        def __new__(cls, *args, **kwargs):
            nonlocal constructor_count
            with count_lock:
                constructor_count += 1
            constructor_entered.set()
            assert release_constructor.wait(timeout=10)
            return original_index(*args, **kwargs)

    monkeypatch.setattr(ports_module, "PortSpatialIndex", CountingSpatialIndex)

    def access_index(_: int):
        start.wait(timeout=10)
        index = registry._spatial_index
        results = index.nearest(
            36.8,
            34.65,
            country_code=None,
            limit=5,
            max_distance_nmi=None,
        )
        return index, results

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(access_index, index) for index in range(workers)]
        start.wait(timeout=10)
        assert constructor_entered.wait(timeout=10)
        release_constructor.set()
        values = [future.result(timeout=10) for future in futures]

    indexes = [index for index, _ in values]
    results = [result for _, result in values]
    assert constructor_count == 1
    assert len({id(index) for index in indexes}) == 1
    assert all(result == results[0] for result in results)


def test_spatial_index_initialization_retries_after_failure(monkeypatch) -> None:
    import harborly.ports as ports_module

    original_index = ports_module.PortSpatialIndex
    registry = PortRegistry.bundled()
    constructor_count = 0

    class FailOnceSpatialIndex:
        def __new__(cls, *args, **kwargs):
            nonlocal constructor_count
            constructor_count += 1
            if constructor_count == 1:
                raise RuntimeError("controlled initialization failure")
            return original_index(*args, **kwargs)

    monkeypatch.setattr(ports_module, "PortSpatialIndex", FailOnceSpatialIndex)

    with pytest.raises(RuntimeError, match="controlled initialization failure"):
        _ = registry._spatial_index

    initialized = registry._spatial_index

    assert registry._spatial_index is initialized
    assert constructor_count == 2


def test_search_validation_invalid_minimum_score_raises(
    registry: PortRegistry,
) -> None:
    with pytest.raises(ValueError, match="minimum_score"):
        registry.search("Istanbul", minimum_score=150.0)
