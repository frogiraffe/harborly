"""Deprecated import path. The reference parsers moved to sea_mile.sources in 0.7."""

import warnings

from sea_mile.sources import parse_unlocode_coordinates, parse_wpi_dms

warnings.warn(
    "sea_mile.reference moved to sea_mile.sources in 0.7. "
    "Import these names from sea_mile.sources instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["parse_unlocode_coordinates", "parse_wpi_dms"]
