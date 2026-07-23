"""Deprecated import path. The text helpers moved to sea_mile.text in 0.7."""

import warnings

from sea_mile.text import canonical_key, normalize_display_text

warnings.warn(
    "sea_mile.normalization moved to sea_mile.text in 0.7. "
    "Import these names from sea_mile.text instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["canonical_key", "normalize_display_text"]
