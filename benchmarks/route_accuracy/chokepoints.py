"""Named passages a route can be checked against.

Each passage is a longitude/latitude box rather than a polygon. A box is enough
to answer "did this route go through Suez", needs no geometry dependency, and
cannot silently mis-handle antimeridian or winding-order cases the way a hand
drawn polygon can. Boxes are deliberately tight around the waterway so a route
passing nearby without transiting it does not register.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Passage:
    """A named box in longitude/latitude degrees."""

    name: str
    min_longitude: float
    max_longitude: float
    min_latitude: float
    max_latitude: float

    def contains(self, longitude: float, latitude: float) -> bool:
        return (
            self.min_longitude <= longitude <= self.max_longitude
            and self.min_latitude <= latitude <= self.max_latitude
        )


PASSAGES: tuple[Passage, ...] = (
    Passage("suez_canal", 32.20, 32.75, 29.85, 31.35),
    Passage("panama_canal", -80.10, -79.35, 8.80, 9.45),
    Passage("gibraltar", -5.95, -5.15, 35.70, 36.25),
    Passage("bosphorus", 28.85, 29.25, 40.95, 41.35),
    Passage("dardanelles", 26.05, 26.85, 39.95, 40.55),
    Passage("malacca", 98.40, 104.20, 0.80, 6.20),
    Passage("bab_el_mandeb", 43.10, 43.70, 12.40, 12.95),
    Passage("danish_straits", 10.40, 13.20, 54.40, 56.60),
    Passage("dover_strait", 0.90, 2.10, 50.55, 51.25),
    Passage("cape_of_good_hope", 16.80, 20.60, -36.20, -33.80),
    # Magellan sits north of Cape Horn and the two boxes do not overlap, so a
    # route through the strait does not register as rounding the cape.
    Passage("strait_of_magellan", -75.00, -68.00, -54.50, -52.00),
    Passage("cape_horn", -70.00, -66.50, -56.50, -54.80),
    Passage("strait_of_hormuz", 55.80, 57.20, 25.80, 27.10),
)

PASSAGES_BY_NAME = {passage.name: passage for passage in PASSAGES}


def passages_used(coordinates: list[list[float]]) -> frozenset[str]:
    """Return the names of every passage a route's vertices fall inside."""

    used: set[str] = set()
    for point in coordinates:
        longitude, latitude = float(point[0]), float(point[1])
        for passage in PASSAGES:
            if passage.name not in used and passage.contains(longitude, latitude):
                used.add(passage.name)
    return frozenset(used)
