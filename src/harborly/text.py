"""String normalization without destroying the original source text."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")


def normalize_display_text(value: object) -> str:
    """Normalize Unicode and whitespace while preserving accents."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE.sub(" ", normalized)


def canonical_key(value: object) -> str:
    """Create an accent/punctuation-insensitive key for candidate generation."""

    display = normalize_display_text(value).replace("ı", "i")
    decomposed = unicodedata.normalize("NFKD", display.casefold())
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return _WHITESPACE.sub(" ", _NON_ALPHANUMERIC.sub(" ", without_marks)).strip()
