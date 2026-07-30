import pandas as pd

from sea_mile.canonical import assign_canonical_ids_with_evidence
from sea_mile.geo import great_circle_nmi


def _make_registry(**kwargs):
    """Create a minimal registry DataFrame for canonical ID tests."""
    defaults = {
        "registry_id": [],
        "canonical_name": [],
        "country_code": [],
        "unlocode": [],
        "latitude": [],
        "longitude": [],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


def test_direct_unlocode():
    df = _make_registry(
        registry_id=["REG:1"],
        canonical_name=["NEW YORK"],
        country_code=["US"],
        unlocode=["USNYC"],
        latitude=[40.71],
        longitude=[-74.00],
    )
    df_out, evidence = assign_canonical_ids_with_evidence(df)

    assert len(evidence) == 1
    ev = evidence[0]
    assert ev.registry_id == "REG:1"
    assert ev.canonical_id == "USNYC"
    assert ev.method == "unlocode_direct"
    assert ev.source_registry_id is None
    assert ev.distance_nmi is None


def test_coordinate_match():
    # One row with UN/LOCODE, one without but same name/country
    df = _make_registry(
        registry_id=["WPI:001", "REG:2"],
        canonical_name=["NEW YORK", "NEW YORK"],
        country_code=["US", "US"],
        unlocode=["USNYC", pd.NA],
        latitude=[40.71, 40.72],
        longitude=[-74.00, -74.01],
    )
    df_out, evidence = assign_canonical_ids_with_evidence(df)

    assert len(evidence) == 2

    # Find the evidence for the coordinate match
    coord_ev = [e for e in evidence if e.registry_id == "REG:2"][0]

    assert coord_ev.canonical_id == "USNYC"
    assert coord_ev.method == "coordinate_match"
    # This will fail until the bug is fixed.
    assert coord_ev.source_registry_id == "WPI:001"
    assert coord_ev.distance_nmi is not None
    assert coord_ev.matched_by == "name+country+coordinate"


def test_synthetic_canonical_id():
    df = _make_registry(
        registry_id=["REG:3"],
        canonical_name=["SOME PLACE"],
        country_code=["US"],
        unlocode=[pd.NA],
        latitude=[45.0],
        longitude=[-90.0],
    )
    df_out, evidence = assign_canonical_ids_with_evidence(df)

    assert len(evidence) == 1
    ev = evidence[0]
    assert ev.registry_id == "REG:3"
    assert ev.canonical_id.startswith("SM-")
    assert ev.method == "synthetic"
    assert ev.source_registry_id is None
    assert ev.distance_nmi is None


def test_deterministic_tie_break():
    # Two identical targets for a coordinate match
    df = _make_registry(
        registry_id=["WPI:001", "WPI:002", "REG:4"],
        canonical_name=["NEW YORK", "NEW YORK", "NEW YORK"],
        country_code=["US", "US", "US"],
        unlocode=["USNYC", "USNYD", pd.NA],
        latitude=[40.71, 40.71, 40.715],
        longitude=[-74.00, -74.00, -74.005],
    )
    df_out, evidence = assign_canonical_ids_with_evidence(df)

    assert len(evidence) == 3
    coord_ev = [e for e in evidence if e.registry_id == "REG:4"][0]

    assert coord_ev.method == "coordinate_match"
    # Assuming tie-break sorts and picks the first one (USNYC -> WPI:001)
    assert coord_ev.source_registry_id == "WPI:001"
    assert coord_ev.canonical_id == "USNYC"


def test_difference_between_canonical_id_and_source_registry_id():
    df = _make_registry(
        registry_id=["SOURCE_REG_1", "TARGET_REG_1"],
        canonical_name=["TEST PORT", "TEST PORT"],
        country_code=["XX", "XX"],
        unlocode=["XXTST", pd.NA],
        latitude=[10.0, 10.01],
        longitude=[20.0, 20.01],
    )
    df_out, evidence = assign_canonical_ids_with_evidence(df)

    coord_ev = [e for e in evidence if e.registry_id == "TARGET_REG_1"][0]

    assert coord_ev.canonical_id == "XXTST"
    assert coord_ev.source_registry_id == "SOURCE_REG_1"
    assert coord_ev.canonical_id != coord_ev.source_registry_id


def test_nearby_codeless_records_share_one_synthetic_id():
    # 0.02 degrees of latitude is about 1.2 nmi, far inside the 25 nmi
    # agreement threshold, but it straddles a 0.1-degree rounding bucket.
    df = _make_registry(
        registry_id=["REG:A", "REG:B"],
        canonical_name=["SEASIDE", "SEASIDE"],
        country_code=["XX", "XX"],
        unlocode=[pd.NA, pd.NA],
        latitude=[40.04, 40.06],
        longitude=[20.0, 20.0],
    )
    canonical_ids, _ = assign_canonical_ids_with_evidence(df)

    assert len(set(canonical_ids)) == 1


def test_synthetic_clusters_never_span_more_than_the_agreement_radius():
    # 0.4 degrees of latitude is about 24 nmi. REG:A sits between the other two
    # and is within 25 nmi of each, but REG:B and REG:C are 48 nmi apart. Growing
    # a cluster around a single leader would chain all three into one identity.
    df = _make_registry(
        registry_id=["REG:A", "REG:B", "REG:C"],
        canonical_name=["COVE", "COVE", "COVE"],
        country_code=["XX", "XX", "XX"],
        unlocode=[pd.NA, pd.NA, pd.NA],
        latitude=[0.0, 0.4, -0.4],
        longitude=[0.0, 0.0, 0.0],
    )
    canonical_ids, _ = assign_canonical_ids_with_evidence(df)

    frame = df.assign(canonical_id=canonical_ids)
    for _, group in frame.groupby("canonical_id"):
        spread = max(
            great_circle_nmi(
                first.latitude, first.longitude, second.latitude, second.longitude
            )
            for first in group.itertuples()
            for second in group.itertuples()
        )
        assert spread <= 25.0
