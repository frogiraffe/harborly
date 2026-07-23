"""Deprecated import path. The OpenStreetMap parser moved to sea_mile.sources in 0.7."""

import warnings

from sea_mile.sources import load_osm_port_archive

warnings.warn(
    "sea_mile.osm moved to sea_mile.sources in 0.7. "
    "Import load_osm_port_archive from sea_mile.sources instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["load_osm_port_archive"]
