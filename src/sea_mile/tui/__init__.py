"""Interactive terminal port search over a local registry, built on Textual.

Re-exports :class:`SeaMileTUI` and :func:`run` for backward compatibility
with ``from sea_mile.tui import SeaMileTUI`` and ``sea_mile.tui.run()``.
"""

from __future__ import annotations

from sea_mile.tui.app import SeaMileTUI, run

__all__ = ["SeaMileTUI", "run"]
