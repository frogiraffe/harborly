"""Deprecated import path. Registry building moved to sea_mile.build in 0.7."""

import warnings

from sea_mile.build import (
    REGISTRY_SCHEMA_VERSION,
    UNLOCODE_COLUMNS,
    build_reference_registry,
    registry_content_hash,
)

warnings.warn(
    "sea_mile.registry_build moved to sea_mile.build in 0.7. "
    "Import these names from sea_mile.build instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "REGISTRY_SCHEMA_VERSION",
    "UNLOCODE_COLUMNS",
    "build_reference_registry",
    "registry_content_hash",
]
