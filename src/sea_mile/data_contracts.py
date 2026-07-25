"""Strict Pandera contracts for human-reviewed and matrix-shaped data."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pandera.pandas as pa

_NON_EMPTY = pa.Check.str_length(min_value=1)
_LATITUDE = pa.Check.in_range(-90.0, 90.0)
_LONGITUDE = pa.Check.in_range(-180.0, 180.0)

REVIEW_SCHEMA = pa.DataFrameSchema(
    {
        "row_id": pa.Column(str, _NON_EMPTY, nullable=False, coerce=True),
        "input_name": pa.Column(str, nullable=False, coerce=True),
        "input_country": pa.Column(str, nullable=False, coerce=True),
        "status": pa.Column(
            str,
            pa.Check.isin(["review_required", "unresolved"]),
            nullable=False,
            coerce=True,
        ),
        "reason_code": pa.Column(str, _NON_EMPTY, nullable=False, coerce=True),
        "candidate_registry_id": pa.Column(str, nullable=True, coerce=True),
        "candidate_provider": pa.Column(str, nullable=True, coerce=True),
        "candidate_name": pa.Column(str, nullable=True, coerce=True),
        "candidate_country_code": pa.Column(str, nullable=True, coerce=True),
        "candidate_latitude": pa.Column(float, _LATITUDE, nullable=True, coerce=True),
        "candidate_longitude": pa.Column(float, _LONGITUDE, nullable=True, coerce=True),
        "candidate_unlocode": pa.Column(str, nullable=True, coerce=True),
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
        "row_id": pa.Column(str, _NON_EMPTY, nullable=False, unique=True, coerce=True),
        "chosen_registry_id": pa.Column(str, _NON_EMPTY, nullable=False, coerce=True),
    },
    strict=True,
    ordered=True,
    name="review_decisions_csv",
)

MATRIX_EDGE_SCHEMA = pa.DataFrameSchema(
    {
        "origin_id": pa.Column(str, _NON_EMPTY, nullable=False, coerce=True),
        "destination_id": pa.Column(str, _NON_EMPTY, nullable=False, coerce=True),
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
    if not np.allclose(values, values.T) or not np.allclose(
        np.diag(values), np.zeros(size)
    ):
        raise pa.errors.SchemaError(
            MATRIX_EDGE_SCHEMA,
            matrix,
            "distance matrix must be symmetric with a zero diagonal",
        )
    return validated
