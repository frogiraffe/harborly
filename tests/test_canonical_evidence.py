import pandas as pd

from sea_mile.canonical import assign_canonical_ids_with_evidence


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
