"""The bundled artifact must agree with the code that derives its columns.

`canonical_id` is shipped precomputed inside `port_registry.parquet`, and
`PortRegistry` reuses that column instead of recomputing it. A change to the
canonical algorithm therefore has no effect on the bundled registry until the
artifact is rebuilt, and nothing else in the suite compares the two.
"""

from __future__ import annotations

import json

import pandas as pd

from sea_mile._registry_data import bundled_data_directory
from sea_mile.build.registry import registry_content_hash
from sea_mile.canonical import assign_canonical_ids


def _bundled() -> tuple[pd.DataFrame, pd.DataFrame]:
    directory = bundled_data_directory()
    return (
        pd.read_parquet(directory / "port_registry.parquet"),
        pd.read_parquet(directory / "port_aliases.parquet"),
    )


def test_shipped_canonical_ids_match_the_current_algorithm() -> None:
    registry, _ = _bundled()

    recomputed = assign_canonical_ids(registry.drop(columns=["canonical_id"]))

    drifted = sum(
        1
        for shipped, current in zip(registry["canonical_id"], recomputed, strict=True)
        if shipped != current
    )
    assert drifted == 0, (
        f"{drifted} of {len(registry)} bundled canonical IDs no longer match "
        "assign_canonical_ids; rebuild the bundled artifact"
    )


def test_manifest_content_hash_matches_the_shipped_artifact() -> None:
    registry, aliases = _bundled()
    manifest = json.loads(
        (bundled_data_directory() / "registry_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["registry_content_hash"] == registry_content_hash(registry, aliases)
