from __future__ import annotations

import pandas as pd

from sea_mile.registry_build import _provider_manifest_entry


def test_provider_manifest_entry_handles_empty_frame() -> None:
    entry = _provider_manifest_entry(pd.DataFrame(), pd.DataFrame())

    assert entry == {"records": 0, "records_with_coordinates": 0, "aliases": 0}


def test_provider_manifest_entry_counts_coordinate_records() -> None:
    registry = pd.DataFrame(
        [
            {"latitude": 1.0, "longitude": 2.0},
            {"latitude": None, "longitude": None},
        ]
    )
    aliases = pd.DataFrame([{"alias": "a"}, {"alias": "b"}, {"alias": "c"}])

    entry = _provider_manifest_entry(registry, aliases)

    assert entry == {"records": 2, "records_with_coordinates": 1, "aliases": 3}
