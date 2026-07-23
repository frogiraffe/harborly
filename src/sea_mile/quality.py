"""Deprecated import path. The coordinate helpers moved to sea_mile.geo in 0.7."""

import warnings

from sea_mile.geo import CoordinateCheck, great_circle_nmi, validate_coordinate

warnings.warn(
    "sea_mile.quality moved to sea_mile.geo in 0.7. "
    "Import these names from sea_mile.geo instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["CoordinateCheck", "great_circle_nmi", "validate_coordinate"]
