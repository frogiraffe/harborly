from __future__ import annotations

import pandas as pd
import pytest

from sea_mile import (
    AmbiguousPortError,
    PortNotFoundError,
    PortRegistry,
    RegistryDataError,
)


def registry_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "registry_id": "WPI:1",
                "provider": "NGA_WPI",
                "provider_id": "1",
                "country_code": "TR",
                "canonical_name": "Mersin",
                "latitude": 36.8,
                "longitude": 34.65,
                "unlocode": "TRMER",
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
            {
                "registry_id": "UNLOCODE:TRMER",
                "provider": "UN_LOCODE",
                "provider_id": "TRMER",
                "country_code": "TR",
                "canonical_name": "Mersin",
                "latitude": 36.8,
                "longitude": 34.63,
                "unlocode": "TRMER",
                "function_code": "1-------",
                "source_version": "test",
                "coordinate_resolution": "arc_minute",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
            {
                "registry_id": "WPI:2",
                "provider": "NGA_WPI",
                "provider_id": "2",
                "country_code": "GR",
                "canonical_name": "Piraeus",
                "latitude": 37.94,
                "longitude": 23.63,
                "unlocode": "GRPIR",
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
            {
                "registry_id": "WPI:3",
                "provider": "NGA_WPI",
                "provider_id": "3",
                "country_code": "TR",
                "canonical_name": "Piraeus",
                "latitude": 40.0,
                "longitude": 26.0,
                "unlocode": "TRXXX",
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
        ]
    )


def alias_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "registry_id": "WPI:1",
                "provider": "NGA_WPI",
                "alias": "Mersin",
                "alias_key": "mersin",
                "alias_type": "primary",
            },
            {
                "registry_id": "UNLOCODE:TRMER",
                "provider": "UN_LOCODE",
                "alias": "Mersin",
                "alias_key": "mersin",
                "alias_type": "primary",
            },
            {
                "registry_id": "WPI:2",
                "provider": "NGA_WPI",
                "alias": "Piraeus",
                "alias_key": "piraeus",
                "alias_type": "primary",
            },
            {
                "registry_id": "WPI:3",
                "provider": "NGA_WPI",
                "alias": "Piraeus",
                "alias_key": "piraeus",
                "alias_type": "primary",
            },
        ]
    )


@pytest.fixture
def registry() -> PortRegistry:
    return PortRegistry(registry_frame(), alias_frame())


def test_exact_search_keeps_source_provenance(registry: PortRegistry) -> None:
    results = registry.search("Mersin", country_code="TR")

    assert [result.port.registry_id for result in results] == [
        "WPI:1",
        "UNLOCODE:TRMER",
    ]
    assert all(result.match_method == "exact_alias" for result in results)


def test_fuzzy_search_respects_country_filter(registry: PortRegistry) -> None:
    results = registry.search("Pireus", country_code="GR")

    assert len(results) == 1
    assert results[0].port.registry_id == "WPI:2"
    assert results[0].match_method == "fuzzy_alias"


def test_search_caches_repeated_queries_but_returns_independent_lists(
    registry: PortRegistry,
) -> None:
    first = registry.search("Mersin", country_code="TR")
    second = registry.search("Mersin", country_code="TR")

    assert first == second
    assert first is not second
    first.clear()
    assert registry.search("Mersin", country_code="TR") == second
    assert registry._search_cached.cache_info().hits >= 1


def test_short_query_with_a_prefix_match_still_returns_it(
    registry: PortRegistry,
) -> None:
    # Prefix matching stays available at any length - useful for
    # browsing ("Me" -> every alias starting with "me").
    results = registry.search("Me", country_code="TR")

    assert [result.port.registry_id for result in results] == [
        "WPI:1",
        "UNLOCODE:TRMER",
    ]
    assert all(result.match_method == "prefix_alias" for result in results)


def test_short_query_without_a_prefix_match_skips_fuzzy(
    registry: PortRegistry,
) -> None:
    # "in" scores 90 via fuzz.WRatio against "mersin" despite not being a
    # prefix of it. Below _MIN_FUZZY_QUERY_LENGTH, edit-distance fuzzy
    # ranking is not meaningful (a global alias pool has too many
    # equally-plausible candidates), so this must not fall through to it.
    assert registry.search("in", country_code="TR") == []


def test_prefix_match_ranks_ahead_of_generic_fuzzy_noise() -> None:
    # "Somers" scores 90 via fuzz.WRatio against "Mers" (a coincidental
    # near-substring match) despite not starting with it, while "Mersin"
    # is a literal prefix. The prefix match must come first and be
    # labeled distinctly, not be indistinguishable fuzzy noise.
    records = pd.concat(
        [
            registry_frame(),
            pd.DataFrame(
                [
                    {
                        "registry_id": "GEONAMES:1",
                        "provider": "GEONAMES",
                        "provider_id": "1",
                        "country_code": "TR",
                        "canonical_name": "Somers",
                        "latitude": 38.0,
                        "longitude": 24.0,
                        "unlocode": None,
                        "function_code": "P.PRT",
                        "source_version": "test",
                        "coordinate_resolution": "decimal_degrees_unspecified",
                        "variant_count": 1,
                        "coordinate_conflict": False,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    aliases = pd.concat(
        [
            alias_frame(),
            pd.DataFrame(
                [
                    {
                        "registry_id": "GEONAMES:1",
                        "provider": "GEONAMES",
                        "alias": "Somers",
                        "alias_key": "somers",
                        "alias_type": "primary",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    results = PortRegistry(records, aliases).search("Mers", country_code="TR")

    assert [result.port.registry_id for result in results] == [
        "WPI:1",
        "UNLOCODE:TRMER",
        "GEONAMES:1",
    ]
    assert results[0].match_method == "prefix_alias"
    assert results[0].name_score == 95.0
    assert results[-1].match_method == "fuzzy_alias"


def test_resolve_caches_repeated_queries(registry: PortRegistry) -> None:
    first = registry.resolve("TRMER")
    second = registry.resolve("TRMER")

    assert first == second
    assert registry._resolve_cached.cache_info().hits >= 1


def test_search_by_unlocode_suppresses_fuzzy_noise() -> None:
    # "Trimer" scores ~91 via fuzz.WRatio against the raw code string
    # "trmer" - high enough to pass the default threshold on its own. A
    # code match must still take full precedence over that noise.
    records = pd.concat(
        [
            registry_frame(),
            pd.DataFrame(
                [
                    {
                        "registry_id": "WPI:99",
                        "provider": "NGA_WPI",
                        "provider_id": "99",
                        "country_code": "FR",
                        "canonical_name": "Trimer",
                        "latitude": 48.0,
                        "longitude": -4.0,
                        "unlocode": "FRTRI",
                        "function_code": "port",
                        "source_version": "test",
                        "coordinate_resolution": "arc_second",
                        "variant_count": 1,
                        "coordinate_conflict": False,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    aliases = pd.concat(
        [
            alias_frame(),
            pd.DataFrame(
                [
                    {
                        "registry_id": "WPI:99",
                        "provider": "NGA_WPI",
                        "alias": "Trimer",
                        "alias_key": "trimer",
                        "alias_type": "primary",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    results = PortRegistry(records, aliases).search("TRMER")

    assert [result.port.registry_id for result in results] == [
        "WPI:1",
        "UNLOCODE:TRMER",
    ]
    assert all(result.match_method == "exact_unlocode" for result in results)


def test_fuzzy_search_excludes_alias_far_shorter_than_the_query() -> None:
    # "Re" scores 90 via fuzz.WRatio against "Pireus" (well above the
    # default 75 threshold) purely because it is a short substring - a
    # length-ratio floor should drop it even though the raw score alone
    # would let it through.
    records = pd.concat(
        [
            registry_frame(),
            pd.DataFrame(
                [
                    {
                        "registry_id": "GEONAMES:1",
                        "provider": "GEONAMES",
                        "provider_id": "1",
                        "country_code": "GR",
                        "canonical_name": "Re",
                        "latitude": 38.0,
                        "longitude": 24.0,
                        "unlocode": None,
                        "function_code": "P.PRT",
                        "source_version": "test",
                        "coordinate_resolution": "decimal_degrees_unspecified",
                        "variant_count": 1,
                        "coordinate_conflict": False,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    aliases = pd.concat(
        [
            alias_frame(),
            pd.DataFrame(
                [
                    {
                        "registry_id": "GEONAMES:1",
                        "provider": "GEONAMES",
                        "alias": "Re",
                        "alias_key": "re",
                        "alias_type": "primary",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    results = PortRegistry(records, aliases).search("Pireus", country_code="GR")

    assert [result.port.registry_id for result in results] == ["WPI:2"]


def test_search_recognizes_bare_unlocode(registry: PortRegistry) -> None:
    results = registry.search("TRMER")

    assert [result.port.registry_id for result in results] == [
        "WPI:1",
        "UNLOCODE:TRMER",
    ]
    assert all(result.match_method == "exact_unlocode" for result in results)
    assert all(result.name_score == 100.0 for result in results)


def test_unlocode_resolution_prefers_coordinate_rich_official_source(
    registry: PortRegistry,
) -> None:
    port = registry.resolve("TRMER")

    assert port.registry_id == "WPI:1"
    assert port.provider == "NGA_WPI"


def test_unlocode_resolution_rejects_large_coordinate_disagreement() -> None:
    records = registry_frame().iloc[[0, 1]].copy()
    records.loc[records["provider"].eq("UN_LOCODE"), "latitude"] = 10.0
    aliases = alias_frame().iloc[[0, 1]].copy()

    with pytest.raises(AmbiguousPortError, match="sources sharing this identity"):
        PortRegistry(records, aliases).resolve("TRMER")


def test_ambiguous_exact_name_requires_explicit_choice(registry: PortRegistry) -> None:
    with pytest.raises(AmbiguousPortError):
        registry.resolve("Piraeus")


def test_same_name_without_shared_identity_code_remains_ambiguous() -> None:
    records = registry_frame().iloc[[0]].copy()
    geonames = records.iloc[0].copy()
    geonames["registry_id"] = "GEONAMES:1"
    geonames["provider"] = "GEONAMES"
    geonames["provider_id"] = "1"
    geonames["unlocode"] = None
    records = pd.concat([records, geonames.to_frame().T], ignore_index=True)
    aliases = alias_frame().iloc[[0]].copy()
    geonames_alias = aliases.iloc[0].copy()
    geonames_alias["registry_id"] = "GEONAMES:1"
    geonames_alias["provider"] = "GEONAMES"
    aliases = pd.concat([aliases, geonames_alias.to_frame().T], ignore_index=True)

    with pytest.raises(AmbiguousPortError):
        PortRegistry(records, aliases).resolve("Mersin")


def test_nearest_returns_distance_ranked_source_records(registry: PortRegistry) -> None:
    results = registry.nearest(36.81, 34.65, country_code="TR", limit=2)

    assert [result.port.registry_id for result in results] == [
        "WPI:1",
        "UNLOCODE:TRMER",
    ]
    assert results[0].distance_nmi < results[1].distance_nmi


def test_nearest_applies_radius_filter(registry: PortRegistry) -> None:
    assert registry.nearest(36.81, 34.65, max_distance_nmi=0.1) == []


def test_nearest_breaks_exact_distance_ties_by_provider_priority() -> None:
    records = pd.DataFrame(
        [
            {
                "registry_id": "UNLOCODE:TIE",
                "provider": "UN_LOCODE",
                "provider_id": "TIE",
                "country_code": "TR",
                "canonical_name": "Tie Port",
                "latitude": 10.0,
                "longitude": 20.0,
                "unlocode": "TRTIE",
                "function_code": "1-------",
                "source_version": "test",
                "coordinate_resolution": "arc_minute",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
            {
                "registry_id": "WPI:TIE",
                "provider": "NGA_WPI",
                "provider_id": "TIE",
                "country_code": "TR",
                "canonical_name": "Tie Port",
                "latitude": 10.0,
                "longitude": 20.0,
                "unlocode": "TRTIE",
                "function_code": "port",
                "source_version": "test",
                "coordinate_resolution": "arc_second",
                "variant_count": 1,
                "coordinate_conflict": False,
            },
        ]
    )
    aliases = pd.DataFrame(
        [
            {
                "registry_id": "UNLOCODE:TIE",
                "provider": "UN_LOCODE",
                "alias": "Tie Port",
                "alias_key": "tie port",
                "alias_type": "primary",
            },
            {
                "registry_id": "WPI:TIE",
                "provider": "NGA_WPI",
                "alias": "Tie Port",
                "alias_key": "tie port",
                "alias_type": "primary",
            },
        ]
    )

    results = PortRegistry(records, aliases).nearest(10.0, 20.0)

    # registry_id alone would sort "UNLOCODE:TIE" first. Provider priority
    # must win the tie instead, putting the NGA_WPI record first.
    assert [result.port.registry_id for result in results] == [
        "WPI:TIE",
        "UNLOCODE:TIE",
    ]
    assert results[0].distance_nmi == results[1].distance_nmi == 0.0


def test_nearest_kdtree_overfetch_margin_widens_for_large_tie_clusters() -> None:
    # 20 exact ties with limit=5 forces k=min(5+8,20)=13 on the k-d tree
    # path (when scipy is installed) - fewer than all 20 tied points. The
    # correct top-5 by registry_id must still come out right, which only
    # holds if the under-fetch is detected and rescued with a wider query.
    suffixes = [f"{n:02d}" for n in range(1, 21)]
    shuffled = suffixes[::-1]
    records = pd.DataFrame(
        [
            {
                "registry_id": f"GEONAMES:{suffix}",
                "provider": "GEONAMES",
                "provider_id": suffix,
                "country_code": "TR",
                "canonical_name": "Tie Port",
                "latitude": 10.0,
                "longitude": 20.0,
                "unlocode": None,
                "function_code": "P.PRT",
                "source_version": "test",
                "coordinate_resolution": "decimal_degrees_unspecified",
                "variant_count": 1,
                "coordinate_conflict": False,
            }
            for suffix in shuffled
        ]
    )
    aliases = pd.DataFrame(
        [
            {
                "registry_id": f"GEONAMES:{suffix}",
                "provider": "GEONAMES",
                "alias": "Tie Port",
                "alias_key": "tie port",
                "alias_type": "primary",
            }
            for suffix in shuffled
        ]
    )

    results = PortRegistry(records, aliases).nearest(10.0, 20.0, limit=5)

    assert [result.port.registry_id for result in results] == [
        "GEONAMES:01",
        "GEONAMES:02",
        "GEONAMES:03",
        "GEONAMES:04",
        "GEONAMES:05",
    ]
    assert all(result.distance_nmi == 0.0 for result in results)


def test_missing_port_has_actionable_error(registry: PortRegistry) -> None:
    with pytest.raises(PortNotFoundError, match="use search"):
        registry.resolve("Definitely Missing")


def test_incomplete_schema_is_rejected() -> None:
    with pytest.raises(RegistryDataError, match="schema is incomplete"):
        PortRegistry(registry_frame().drop(columns="source_version"), alias_frame())


def _record(registry_id, provider, country, name, unlocode, lat, lon) -> dict:
    return {
        "registry_id": registry_id,
        "provider": provider,
        "provider_id": registry_id.split(":", 1)[1],
        "country_code": country,
        "canonical_name": name,
        "latitude": lat,
        "longitude": lon,
        "unlocode": unlocode,
        "function_code": "port",
        "source_version": "test",
        "coordinate_resolution": "test",
        "variant_count": 1,
        "coordinate_conflict": False,
    }


def _alias(registry_id, provider, name) -> dict:
    from sea_mile import canonical_key

    return {
        "registry_id": registry_id,
        "provider": provider,
        "alias": name,
        "alias_key": canonical_key(name),
        "alias_type": "primary",
    }


def test_search_grouped_collapses_shared_unlocode(registry: PortRegistry) -> None:
    groups = registry.search_grouped("Mersin", country_code="TR")

    assert len(groups) == 1
    group = groups[0]
    assert group.unlocode == "TRMER"
    assert group.best_id == "WPI:1"
    assert group.sources == ("NGA_WPI", "UN_LOCODE")
    assert {member.registry_id for member in group.members} == {
        "WPI:1",
        "UNLOCODE:TRMER",
    }
    assert group.coordinate_conflict is False
    assert group.has_coordinates


def test_search_grouped_keeps_distinct_ports_separate(registry: PortRegistry) -> None:
    groups = registry.search_grouped("Piraeus")

    assert {group.best_id for group in groups} == {"WPI:2", "WPI:3"}


def test_search_grouped_flags_coordinate_conflict() -> None:
    records = pd.DataFrame(
        [
            _record("WPI:10", "NGA_WPI", "ZZ", "Twin", "ZZAAA", 10.0, 10.0),
            _record("UNLOCODE:ZZAAA", "UN_LOCODE", "ZZ", "Twin", "ZZAAA", 40.0, 40.0),
        ]
    )
    aliases = pd.DataFrame(
        [
            _alias("WPI:10", "NGA_WPI", "Twin"),
            _alias("UNLOCODE:ZZAAA", "UN_LOCODE", "Twin"),
        ]
    )
    registry = PortRegistry(records, aliases)

    groups = registry.search_grouped("Twin")

    assert len(groups) == 1
    assert groups[0].coordinate_conflict is True
    assert groups[0].latitude is None
    assert groups[0].longitude is None


def test_search_grouped_merges_geonames_by_name_and_proximity() -> None:
    records = pd.DataFrame(
        [
            _record("WPI:20", "NGA_WPI", "ZZ", "Harbor", "ZZBBB", 20.0, 20.0),
            _record("GEONAMES:20", "GEONAMES", "ZZ", "Harbor", None, 20.05, 20.05),
            _record("GEONAMES:21", "GEONAMES", "ZZ", "Harbor", None, 50.0, 50.0),
        ]
    )
    aliases = pd.DataFrame(
        [
            _alias("WPI:20", "NGA_WPI", "Harbor"),
            _alias("GEONAMES:20", "GEONAMES", "Harbor"),
            _alias("GEONAMES:21", "GEONAMES", "Harbor"),
        ]
    )
    registry = PortRegistry(records, aliases)

    groups = registry.search_grouped("Harbor")

    assert len(groups) == 2
    merged = next(group for group in groups if group.best_id == "WPI:20")
    assert {member.registry_id for member in merged.members} == {
        "WPI:20",
        "GEONAMES:20",
    }
    far = next(group for group in groups if group.best_id == "GEONAMES:21")
    assert len(far.members) == 1


def test_match_names_flags_location_disagreement() -> None:
    records = pd.DataFrame(
        [
            _record("WPI:30", "NGA_WPI", "US", "Hamilton", "USXXX", 30.0, -90.0),
            _record(
                "UNLOCODE:USYYY", "UN_LOCODE", "US", "Hamilton", "USYYY", 45.0, -70.0
            ),
        ]
    )
    aliases = pd.DataFrame(
        [
            _alias("WPI:30", "NGA_WPI", "Hamilton"),
            _alias("UNLOCODE:USYYY", "UN_LOCODE", "Hamilton"),
        ]
    )
    registry = PortRegistry(records, aliases)

    [result] = registry.match_names(["Hamilton"], country_codes=["US"])

    assert result.status == "review_required"
    assert result.selected_registry_id is None


def test_match_names_auto_resolves_a_single_official_match(
    registry: PortRegistry,
) -> None:
    [result] = registry.match_names(["Mersin"], country_codes=["TR"])

    assert result.status == "auto_resolved"
    assert result.selected_registry_id == "WPI:1"


def test_nearest_grouped_collapses_sources(registry: PortRegistry) -> None:
    groups = registry.nearest_grouped(36.8, 34.64, country_code="TR", limit=5)

    assert groups[0].group.best_id == "WPI:1"
    assert {member.registry_id for member in groups[0].group.members} == {
        "WPI:1",
        "UNLOCODE:TRMER",
    }
    assert groups[0].distance_nmi < 1


def test_group_for_returns_all_sources(registry: PortRegistry) -> None:
    by_code = registry.group_for("TRMER")
    by_id = registry.group_for("UNLOCODE:TRMER")

    assert by_code.best_id == "WPI:1"
    assert by_code.sources == ("NGA_WPI", "UN_LOCODE")
    assert by_id.best_id == by_code.best_id


def test_group_for_gathers_siblings_past_the_search_limit() -> None:
    rows = [
        _record(
            f"WPI:ZZ{index:03d}",
            "NGA_WPI",
            "ZZ",
            "Same",
            f"ZZ{index:03d}",
            10.0 + index,
            10.0,
        )
        for index in range(1, 13)
    ]
    rows.append(_record("GEONAMES:G12", "GEONAMES", "ZZ", "Same", None, 22.0, 10.0))
    records = pd.DataFrame(rows)
    aliases = pd.DataFrame(
        [_alias(row["registry_id"], row["provider"], "Same") for row in rows]
    )
    registry = PortRegistry(records, aliases)

    group = registry.group_for("ZZ012")

    assert group.best_id == "WPI:ZZ012"
    assert {member.registry_id for member in group.members} == {
        "WPI:ZZ012",
        "GEONAMES:G12",
    }


def test_countries_skips_null_country_codes() -> None:
    records = pd.DataFrame(
        [
            _record("WPI:1", "NGA_WPI", "TR", "A", "TRAAA", 10.0, 10.0),
            _record("WPI:2", "NGA_WPI", None, "B", None, 11.0, 11.0),
        ]
    )
    aliases = pd.DataFrame(
        [_alias("WPI:1", "NGA_WPI", "A"), _alias("WPI:2", "NGA_WPI", "B")]
    )

    assert PortRegistry(records, aliases).countries() == ["TR"]


def test_ports_in_country_filters(registry: PortRegistry) -> None:
    ports = registry.ports_in_country("tr")

    assert {port.registry_id for port in ports} == {
        "WPI:1",
        "UNLOCODE:TRMER",
        "WPI:3",
    }


def test_cluster_guard_keeps_distinct_official_codes() -> None:
    records = pd.DataFrame(
        [
            _record("WPI:40", "NGA_WPI", "ZZ", "Twin", "ZZAAA", 10.0, 10.0),
            _record("GEONAMES:40", "GEONAMES", "ZZ", "Twin", None, 10.01, 10.01),
            _record("WPI:41", "NGA_WPI", "ZZ", "Twin", "ZZBBB", 10.02, 10.02),
        ]
    )
    aliases = pd.DataFrame(
        [
            _alias("WPI:40", "NGA_WPI", "Twin"),
            _alias("GEONAMES:40", "GEONAMES", "Twin"),
            _alias("WPI:41", "NGA_WPI", "Twin"),
        ]
    )
    registry = PortRegistry(records, aliases)

    groups = registry.search_grouped("Twin")

    codes = sorted(group.unlocode for group in groups)
    assert codes == ["ZZAAA", "ZZBBB"]


def test_registry_conveniences(registry: PortRegistry) -> None:
    assert "WPI:1" in registry
    assert "MISSING" not in registry
    assert registry.countries() == ["GR", "TR"]
    assert len(registry.ports()) == len(registry)
    assert {port.registry_id for port in registry} == {
        "WPI:1",
        "UNLOCODE:TRMER",
        "WPI:2",
        "WPI:3",
    }


def test_canonical_id_uses_the_shared_unlocode(registry: PortRegistry) -> None:
    group = registry.group_for("TRMER")

    assert group.canonical_id == "TRMER"
    assert all(
        member.canonical_id == "TRMER" for member in group.members if member.unlocode
    )


def test_resolve_canonical_returns_the_group(registry: PortRegistry) -> None:
    group = registry.resolve_canonical("TRMER")

    assert group.canonical_id == "TRMER"
    assert {member.registry_id for member in group.members} == {
        "WPI:1",
        "UNLOCODE:TRMER",
    }

    with pytest.raises(PortNotFoundError):
        registry.resolve_canonical("SM-NOTHING")


def test_canonical_id_attaches_codeless_record_to_a_coded_sibling() -> None:
    records = pd.DataFrame(
        [
            _record("WPI:50", "NGA_WPI", "ZZ", "Harbor", "ZZHBR", 20.0, 20.0),
            _record("GEONAMES:50", "GEONAMES", "ZZ", "Harbor", None, 20.05, 20.05),
            _record("GEONAMES:51", "GEONAMES", "ZZ", "Harbor", None, 60.0, 60.0),
        ]
    )
    aliases = pd.DataFrame(
        [
            _alias("WPI:50", "NGA_WPI", "Harbor"),
            _alias("GEONAMES:50", "GEONAMES", "Harbor"),
            _alias("GEONAMES:51", "GEONAMES", "Harbor"),
        ]
    )
    ports = {port.registry_id: port for port in PortRegistry(records, aliases).ports()}

    assert ports["WPI:50"].canonical_id == "ZZHBR"
    assert ports["GEONAMES:50"].canonical_id == "ZZHBR"
    assert ports["GEONAMES:51"].canonical_id.startswith("SM-")


def test_canonical_ids_are_order_independent() -> None:
    from sea_mile.canonical import assign_canonical_ids

    rows = [
        _record("WPI:50", "NGA_WPI", "ZZ", "Harbor", "ZZHBR", 20.0, 20.0),
        _record("GEONAMES:50", "GEONAMES", "ZZ", "Harbor", None, 20.05, 20.05),
    ]
    frame = pd.DataFrame(rows)
    reversed_frame = pd.DataFrame(list(reversed(rows)))

    forward = dict(zip(frame["registry_id"], assign_canonical_ids(frame), strict=True))
    backward = dict(
        zip(
            reversed_frame["registry_id"],
            assign_canonical_ids(reversed_frame),
            strict=True,
        )
    )

    assert forward == backward


def test_match_series_agrees_with_match_names(registry: PortRegistry) -> None:
    names = ["Mersin", "Piraeus"]
    series_results = registry.match_series(pd.Series(names))
    list_results = registry.match_names(names)
    assert [result.selected_registry_id for result in series_results] == [
        result.selected_registry_id for result in list_results
    ]
    assert [str(result.status) for result in series_results] == [
        str(result.status) for result in list_results
    ]


def test_match_series_treats_missing_values_as_empty(registry: PortRegistry) -> None:
    results = registry.match_series(pd.Series(["Mersin", None, float("nan")]))
    assert [result.selected_registry_id for result in results] == ["WPI:1", None, None]


def test_match_series_applies_the_country_filter(registry: PortRegistry) -> None:
    results = registry.match_series(
        pd.Series(["Piraeus"]), country_codes=pd.Series(["GR"])
    )
    assert results[0].selected_registry_id == "WPI:2"


def test_match_dataframe_appends_enrichment_columns(registry: PortRegistry) -> None:
    frame = pd.DataFrame({"port": ["Mersin"], "ref": ["X-1"]})
    enriched = registry.match_dataframe(frame, name_column="port")
    assert list(enriched["ref"]) == ["X-1"]
    assert enriched.loc[0, "sea_mile_status"] == "auto_resolved"
    assert enriched.loc[0, "sea_mile_registry_id"] == "WPI:1"
    assert enriched.loc[0, "sea_mile_name"] == "Mersin"
    assert enriched.loc[0, "sea_mile_unlocode"] == "TRMER"
    assert "sea_mile_status" not in frame.columns


def test_match_dataframe_uses_the_country_column(registry: PortRegistry) -> None:
    frame = pd.DataFrame({"port": ["Piraeus"], "cc": ["GR"]})
    enriched = registry.match_dataframe(frame, name_column="port", country_column="cc")
    assert enriched.loc[0, "sea_mile_registry_id"] == "WPI:2"


def test_match_dataframe_rejects_an_unknown_column(registry: PortRegistry) -> None:
    frame = pd.DataFrame({"port": ["Mersin"]})
    with pytest.raises(KeyError):
        registry.match_dataframe(frame, name_column="missing")
