# Route benchmark data

## `voyages.csv`

Voyages whose transits are not in dispute, used for structural checks. Each row
names the passages the route must enter and the ones it cannot.

`expected_passages` and `forbidden_passages` are `|`-separated names from
`benchmarks/route_accuracy/chokepoints.py`. Leave `expected_passages` empty for a
voyage that crosses open water without a named chokepoint; the forbidden list
still applies and is what catches a route wandering through the wrong ocean.

Adding a voyage does not need any external data, only a passage claim that is
true by geography.

## `reference_distances.csv`

This file answers the one question the structural checks cannot: how close
the computed distance is to an accepted port-to-port sea distance.

Every row requires a distance taken from a real published source, with the
source recorded per row. Numbers must not be invented, estimated, or copied from
another routing engine — a benchmark that scores this engine against a guess
reports nothing, and scoring it against another engine measures agreement rather
than accuracy.

**Current population (44 rows, added 2026-07-29/30):** every row's distance,
and both ports' coordinates, come from NGA Pub. 151, *Distances Between
Ports*, 11th ed. (2001) — the National Geospatial-Intelligence Agency's
official port-to-port distance tables
(<https://msi.nga.mil/api/publications/download?key=16694076%2FSFH00000%2FPub151bk.pdf&type=view>).
Pub. 151 states its distances are "generally over routes that afford the
safest passage," not strict great-circle, and occasionally favor currents or
avoid ice/traffic-separation zones — this applies uniformly to every row
citing this source; no row mixes in a different convention. Rows were
selected only where **both** the origin and destination also appear as their
own departure-port header in Pub. 151, so each row's coordinates come
straight from the source's own listed positions rather than being looked up
elsewhere. Two rows note the specific route Pub. 151 states the distance
follows (e.g. "via Windward Passage and Crooked Island Passage") where that
context is part of the published figure. One coordinate (Hong Kong's
longitude minutes) had a single-character OCR artifact in the extracted PDF
text ("l0" for "10"); it was corrected after independently verifying it
against Hong Kong's known real-world position, not guessed.

Scoring this population against the current `searoute` backend
(`uv run python -m benchmarks.route_accuracy`) gives 30 scored pairs at
median 2.03% / p90 6.68% absolute percentage error — see
`benchmark-results/route_accuracy.md` for the full table. Two findings worth
knowing about, not bugs in this data:

- 14 of the 44 pairs cross the antimeridian (transpacific routes touching
  Asia/Australia/Pacific-island ports and the US West Coast) and the
  `searoute` backend raises `RoutingError` for all of them ("returned an
  unusable geometry") rather than producing a route at all. They are excluded
  from the error statistics and reported separately as routing failures —
  this is a real backend limitation the curated data surfaced, not a data
  quality problem. See `benchmarks/route_accuracy/__main__.py`, which now
  catches per-pair `RoutingError` instead of crashing the whole benchmark run
  (a real latent bug this population exposed: a single bad pair previously
  took down the entire script).
- The single worst scored outlier is Panama, Panama -> New York (41.5%
  error): the reference figure is explicitly a Panama Canal transit route,
  but the computed distance is close to what going around South America
  would cost, suggesting the backend is not modeling the canal transit for
  this specific pair. Left as an observed finding, not investigated further
  here.

Target coverage remains ~40-60 representative pairs per the original plan;
44 was reached with every row individually hand-verified against the source
text (a deliberately slower process than bulk-parsing the whole 138-page
publication, which was tried first and abandoned after it produced
systematic name-boundary errors -- see the session's handoff notes for
detail). Extending this set further is welcome but should hold the same bar:
both coordinates traceable to the same publication, every row spot-checked
against the raw source text.

Columns:

| Column | Meaning |
| --- | --- |
| `origin_name`, `origin_lat`, `origin_lon` | Origin port and the coordinate used |
| `destination_name`, `destination_lat`, `destination_lon` | Destination and its coordinate |
| `reference_nmi` | Published sea distance in nautical miles |
| `source` | Publication the figure came from |
| `source_url` | Where it can be checked |

Once rows exist, `python -m benchmarks.route_accuracy` reports absolute error,
absolute percentage error, and the median and p90 of both. Aim for coverage
across the cases most likely to be wrong: canal transits, ports whose coordinate
sits up a river, archipelago routing, and voyages with a plausible alternative
around a cape.
