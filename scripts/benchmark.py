"""Benchmark registry construction, search, and nearest-port queries."""

from __future__ import annotations

import argparse
import platform
import random
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd

import sea_mile.spatial
from sea_mile import PortRegistry
from sea_mile._routing_backend import BackendRoute, RoutingConfig
from sea_mile.coordinates import LatLon
from sea_mile.geo import great_circle_nmi
from sea_mile.router import SeaRouter
from sea_mile.text import canonical_key

try:
    import resource as _resource
except ImportError:
    _resource = None

resource: Any = _resource

_LABEL = 22

_PREFIXES = (
    "Port",
    "San",
    "Puerto",
    "Bahia",
    "Cabo",
    "Marina",
    "Haven",
    "Bay",
    "Cape",
    "Santa",
)


class _BenchmarkRoutingBackend:
    name = "benchmark-great-circle"
    version = "1"
    graph_version = "synthetic-1"
    symmetric = True

    def route(
        self, origin: LatLon, destination: LatLon, config: RoutingConfig
    ) -> BackendRoute:
        return BackendRoute(
            distance_nmi=great_circle_nmi(*origin, *destination) * 1.1,
            geometry={
                "type": "LineString",
                "coordinates": [
                    origin.to_lon_lat().as_list(),
                    destination.to_lon_lat().as_list(),
                ],
            },
        )


def _synthetic(count: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = random.Random(20260722)  # nosec B311
    records: list[dict[str, object]] = []
    aliases: list[dict[str, str]] = []
    for index in range(count):
        registry_id = f"WPI:{index}"
        name = f"{rng.choice(_PREFIXES)} {rng.randrange(count // 4 + 1)}"
        country = f"{chr(65 + index % 26)}{chr(65 + (index // 26) % 26)}"
        records.append(
            {
                "registry_id": registry_id,
                "provider": "NGA_WPI",
                "provider_id": str(index),
                "country_code": country,
                "canonical_name": name,
                "latitude": rng.uniform(-80.0, 80.0),
                "longitude": rng.uniform(-179.0, 179.0),
                "unlocode": None,
                "function_code": "port",
                "source_version": "benchmark",
                "coordinate_resolution": "synthetic",
                "variant_count": 1,
                "coordinate_conflict": False,
            }
        )
        aliases.append(
            {
                "registry_id": registry_id,
                "provider": "NGA_WPI",
                "alias": name,
                "alias_key": canonical_key(name),
                "alias_type": "primary",
            }
        )
    return pd.DataFrame(records), pd.DataFrame(aliases)


def _peak_memory_mb() -> float | None:
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return peak / (1024 * 1024)
    return peak / 1024


def _bench(
    label: str, inputs: Sequence[object], call: Callable[[object], object]
) -> None:
    start = time.perf_counter()
    for item in inputs:
        call(item)
    per_op = (time.perf_counter() - start) / len(inputs) * 1000
    print(f"{label:{_LABEL}}{per_op:8.3f} ms/op  ({len(inputs)} distinct)")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Time registry build, search, and nearest on synthetic data."
    )
    parser.add_argument(
        "count",
        nargs="?",
        type=int,
        default=40000,
        help="number of synthetic records to build (default 40000)",
    )
    parser.add_argument(
        "--no-kdtree",
        action="store_true",
        help="disable the scipy k-d tree and measure nearest on the scan path",
    )
    parser.add_argument(
        "--matrix-size",
        type=int,
        default=0,
        help="also build a dense synthetic matrix of this size with one worker",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.no_kdtree:
        sea_mile.spatial.cKDTree = None

    frame, aliases = _synthetic(args.count)
    tree = "scipy" if sea_mile.spatial.cKDTree is not None else "scan only"
    machine = f"{platform.system()} {platform.machine()}"

    print("sea-mile benchmark")
    print(f"{'python':{_LABEL}}{platform.python_version()} on {machine}")
    print(f"{'records':{_LABEL}}{args.count}")
    print(f"{'k-d tree':{_LABEL}}{tree}")

    start = time.perf_counter()
    registry = PortRegistry(frame, aliases)
    print(
        f"{'build registry':{_LABEL}}{(time.perf_counter() - start) * 1000:8.1f} ms\n"
    )

    step = max(1, args.count // 100)
    rows = frame.iloc[::step]
    names = [str(name) for name in rows["canonical_name"]]
    coords = list(zip(rows["latitude"], rows["longitude"], strict=True))
    countries = [str(code) for code in rows["country_code"]]
    prefixes = [prefix[:2] for prefix in _PREFIXES]

    _bench("search exact", names, lambda name: registry.search(str(name), limit=10))
    _bench("search prefix", prefixes, lambda name: registry.search(str(name), limit=10))
    _bench(
        "search fuzzy",
        [f"{name}z" for name in names],
        lambda name: registry.search(str(name), limit=10),
    )
    _bench(
        "search_grouped",
        names,
        lambda name: registry.search_grouped(str(name), limit=10),
    )
    _bench(
        "nearest",
        coords,
        lambda point: registry.nearest(point[0], point[1], limit=10),  # type: ignore[index]
    )
    _bench(
        "nearest + country",
        list(zip(coords, countries, strict=True)),
        lambda item: registry.nearest(
            item[0][0],  # type: ignore[index]
            item[0][1],  # type: ignore[index]
            country_code=item[1],  # type: ignore[index]
            limit=10,
        ),
    )

    if args.matrix_size:
        if not 2 <= args.matrix_size <= args.count:
            raise ValueError("--matrix-size must be between 2 and the record count")
        matrix_ports = registry.ports()[: args.matrix_size]
        router = SeaRouter(_routing_backend=_BenchmarkRoutingBackend())
        started = time.perf_counter()
        matrix = router.distance_matrix(matrix_ports, max_workers=1)
        elapsed = time.perf_counter() - started
        edges = args.matrix_size * (args.matrix_size - 1) // 2
        print(
            f"{'distance matrix':{_LABEL}}{elapsed:8.3f} s  "
            f"({args.matrix_size} ports, {edges:,} routes)"
        )
        if len(matrix) != args.matrix_size:
            raise RuntimeError("matrix benchmark returned an unexpected shape")

    peak = _peak_memory_mb()
    reading = f"{peak:8.1f} MB" if peak is not None else "     n/a"
    print(f"\n{'peak memory':{_LABEL}}{reading}  (process high-water mark)")


if __name__ == "__main__":
    main()
