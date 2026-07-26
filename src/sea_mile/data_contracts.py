"""Strict Pandera contracts for human-reviewed and matrix-shaped data."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pandera.pandas as pa

_NON_EMPTY = pa.Check(lambda values: values.str.strip().str.len().ge(1))
_REGISTRY_ID = pa.Check.str_matches(r"^[A-Z][A-Z0-9_]*:.+$")
_LATITUDE = pa.Check.in_range(-90.0, 90.0)
_LONGITUDE = pa.Check.in_range(-180.0, 180.0)

_REVIEW_STATUSES = ("review_required", "unresolved")

REVIEW_SCHEMA = pa.DataFrameSchema(
    {
        "row_id": pa.Column(str, _NON_EMPTY, nullable=False, coerce=False),
        "input_name": pa.Column(str, nullable=False, coerce=False),
        "input_country": pa.Column(str, nullable=False, coerce=False),
        "status": pa.Column(
            str,
            pa.Check.isin(_REVIEW_STATUSES),
            nullable=False,
            coerce=False,
        ),
        "reason_code": pa.Column(str, _NON_EMPTY, nullable=False, coerce=False),
        "candidate_registry_id": pa.Column(
            str, _REGISTRY_ID, nullable=True, coerce=False
        ),
        "candidate_provider": pa.Column(str, nullable=True, coerce=False),
        "candidate_name": pa.Column(str, nullable=True, coerce=False),
        "candidate_country_code": pa.Column(str, nullable=True, coerce=False),
        "candidate_latitude": pa.Column(float, _LATITUDE, nullable=True, coerce=True),
        "candidate_longitude": pa.Column(float, _LONGITUDE, nullable=True, coerce=True),
        "candidate_unlocode": pa.Column(str, nullable=True, coerce=False),
    },
    checks=pa.Check(
        lambda frame: (
            frame["candidate_latitude"].isna() == frame["candidate_longitude"].isna()
        ),
        error="candidate latitude and longitude must both be present or absent",
    ),
    strict=True,
    ordered=True,
    name="review_csv",
)

REVIEW_DECISIONS_SCHEMA = pa.DataFrameSchema(
    {
        "row_id": pa.Column(str, _NON_EMPTY, nullable=False, unique=True, coerce=False),
        "chosen_registry_id": pa.Column(
            str,
            [_NON_EMPTY, _REGISTRY_ID],
            nullable=False,
            coerce=False,
        ),
    },
    strict=True,
    ordered=True,
    name="review_decisions_csv",
)

MATRIX_EDGE_SCHEMA = pa.DataFrameSchema(
    {
        "origin_id": pa.Column(str, _NON_EMPTY, nullable=False, coerce=False),
        "destination_id": pa.Column(str, _NON_EMPTY, nullable=False, coerce=False),
        "distance_nmi": pa.Column(
            float,
            [pa.Check.ge(0.0), pa.Check(lambda values: np.isfinite(values))],
            nullable=False,
            coerce=True,
        ),
    },
    strict=True,
    ordered=True,
    name="distance_matrix_edges",
)


def validate_review_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate rows written to ``review.csv`` without accepting extra fields."""

    return REVIEW_SCHEMA.validate(frame)


def validate_review_decisions(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the strict human decision contract consumed by the CLI."""

    return REVIEW_DECISIONS_SCHEMA.validate(frame)


def validate_distance_matrix(
    port_ids: Sequence[str], matrix: Sequence[Sequence[float]]
) -> pd.DataFrame:
    """Validate IDs, dimensions, and numeric values in a matrix result."""

    size = len(port_ids)
    if any(not str(port_id).strip() for port_id in port_ids):
        raise pa.errors.SchemaError(
            MATRIX_EDGE_SCHEMA,
            port_ids,
            "distance matrix port IDs must be non-empty",
        )
    if len(set(port_ids)) != size:
        raise pa.errors.SchemaError(
            MATRIX_EDGE_SCHEMA,
            port_ids,
            "distance matrix port IDs must be unique",
        )
    if len(matrix) != size or any(len(row) != size for row in matrix):
        raise pa.errors.SchemaError(
            MATRIX_EDGE_SCHEMA,
            matrix,
            "distance matrix dimensions must match the number of port IDs",
        )
    frame = pd.DataFrame(
        [
            {
                "origin_id": origin_id,
                "destination_id": destination_id,
                "distance_nmi": matrix[row][column],
            }
            for row, origin_id in enumerate(port_ids)
            for column, destination_id in enumerate(port_ids)
        ]
    )
    validated = MATRIX_EDGE_SCHEMA.validate(frame)
    values = np.asarray(matrix, dtype=float)
    if not np.allclose(np.diag(values), np.zeros(size)):
        raise pa.errors.SchemaError(
            MATRIX_EDGE_SCHEMA,
            matrix,
            "distance matrix must have a zero diagonal",
        )
    return validated
