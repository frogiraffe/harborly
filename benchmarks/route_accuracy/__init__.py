"""Structural accuracy benchmark for approximate sea routes.

Most of this needs no external reference data. A route can be checked against
facts that hold regardless of which engine produced it: it has to transit the
passages a voyage between two places must transit, it must not transit ones it
cannot, distances must obey the triangle inequality and the engine's own
symmetry claim, and the port coordinate has to sit close to the graph node the
route actually starts from.

That last one is the most useful single measurement and the least visible: with
``append_orig_dest`` the backend returns the requested coordinate as the first
vertex and the graph node it snapped to as the second, so the snap distance is
already in the geometry and nothing reports it.
"""

from benchmarks.route_accuracy.chokepoints import (
    PASSAGES,
    PASSAGES_BY_NAME,
    Passage,
    passages_used,
)

__all__ = ["PASSAGES", "PASSAGES_BY_NAME", "Passage", "passages_used"]
