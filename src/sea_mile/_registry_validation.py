"""Shared validation for public registry query arguments."""

from __future__ import annotations


def validate_limit(limit: object) -> int:
    """Return a positive integer result limit or raise a stable public error."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    return limit
