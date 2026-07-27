"""Interactive terminal port search over a local registry, built on Textual.

Re-exports :class:`SeaMileTUI` and :func:`run` for backward compatibility
with ``from sea_mile.tui import SeaMileTUI`` and ``sea_mile.tui.run()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sea_mile.tui.app import SeaMileTUI, run

_LAZY_EXPORTS = {
    "SeaMileTUI": "sea_mile.tui.app",
    "run": "sea_mile.tui.app",
}


def __getattr__(name: str) -> object:
    from importlib import import_module

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        value = getattr(import_module(module_name), name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(_LAZY_EXPORTS))


__all__ = ["SeaMileTUI", "run"]
