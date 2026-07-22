"""Command-line interface for the public port registry and sea router."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import io
import json
import logging
import os
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sea_mile.exceptions import SeaMileError
from sea_mile.ports import Port, PortGroup, PortRegistry, source_short_label

logger = logging.getLogger("sea_mile")

_PORT_FIELDS = [field.name for field in dataclasses.fields(Port)]


def _version() -> str:
    try:
        return version("sea-mile")
    except PackageNotFoundError:
        return "0.0.0"


def _parse_coordinate(value: str) -> tuple[float, float] | None:
    if value.count(",") != 1:
        return None
    latitude_text, longitude_text = value.split(",")
    try:
        return float(latitude_text), float(longitude_text)
    except ValueError:
        return None


def _endpoint_port(registry: PortRegistry, value: str, country: str | None) -> Port:
    coordinate = _parse_coordinate(value)
    if coordinate is None:
        return registry.resolve(value, country_code=country)
    from sea_mile.router import _coordinate_port

    return _coordinate_port(value, coordinate[0], coordinate[1])


def _ports_to_csv(ports: Sequence[Port]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_PORT_FIELDS)
    writer.writeheader()
    for port in ports:
        writer.writerow(port.to_dict())
    return buffer.getvalue()


def _default_data_directory() -> Path:
    configured = os.environ.get("SEA_MILE_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    project_data = Path.cwd() / "data" / "reference" / "processed"
    if project_data.exists():
        return project_data
    return Path.home() / ".local" / "share" / "sea-mile" / "reference" / "processed"


def _default_reference_root() -> Path:
    project_reference = Path.cwd() / "data" / "reference"
    if project_reference.exists():
        return project_reference
    return Path.home() / ".local" / "share" / "sea-mile" / "reference"


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for column, cell in enumerate(row):
            widths[column] = max(widths[column], len(cell))
    for line_cells in (headers, *rows):
        line = "  ".join(
            cell.ljust(width) for cell, width in zip(line_cells, widths, strict=True)
        )
        print(line.rstrip())


def _port_lines(port: Port) -> list[str]:
    lines = [
        f"name: {port.name}",
        f"registry_id: {port.registry_id}",
        f"provider: {port.provider} ({port.provider_id})",
        f"country: {port.country_code}",
        f"unlocode: {port.unlocode or '-'}",
        f"function_code: {port.function_code or '-'}",
    ]
    if port.has_coordinates:
        lines.append(f"coordinates: {port.latitude:.4f}, {port.longitude:.4f}")
    else:
        lines.append("coordinates: none on file")
    lines.append(f"source_version: {port.source_version}")
    if port.variant_count > 1:
        lines.append(f"variant_count: {port.variant_count}")
    if port.coordinate_conflict:
        lines.append("warning: coordinate conflict across sources")
    return lines


def _load_registry(args: argparse.Namespace) -> PortRegistry:
    logger.info("loading registry from %s", args.data_dir)
    registry = PortRegistry.from_directory(args.data_dir)
    logger.info("loaded %d records", len(registry))
    return registry


def _cmd_info(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    data_directory = str(args.data_dir.resolve())
    if args.json:
        _print_json(
            {
                "registry_records": len(registry),
                "providers": registry.providers,
                "data_directory": data_directory,
            }
        )
        return 0
    print(f"registry_records: {len(registry)}")
    for provider, count in registry.providers.items():
        print(f"provider {provider}: {count}")
    print(f"data_directory: {data_directory}")
    return 0


def _group_coordinate_cell(group: PortGroup) -> str:
    if group.coordinate_conflict:
        return "conflict"
    if group.has_coordinates:
        return f"{group.latitude:.4f}, {group.longitude:.4f}"
    return "-"


def _cmd_search(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    if args.all_sources:
        results = registry.search(
            args.query,
            country_code=args.country_code,
            limit=args.limit,
            fuzzy=not args.exact_only,
            minimum_score=args.minimum_score,
        )
        if args.json:
            _print_json([result.to_dict() for result in results])
            return 0
        if not results:
            print("no matches")
            return 0
        _print_table(
            ("NAME", "COUNTRY", "PROVIDER", "METHOD", "SCORE", "ID"),
            [
                (
                    result.port.name,
                    result.port.country_code,
                    result.port.provider,
                    result.match_method,
                    f"{result.name_score:.0f}",
                    result.port.registry_id,
                )
                for result in results
            ],
        )
        return 0

    groups = registry.search_grouped(
        args.query,
        country_code=args.country_code,
        limit=args.limit,
        fuzzy=not args.exact_only,
        minimum_score=args.minimum_score,
    )
    if args.json:
        _print_json([group.to_dict() for group in groups])
        return 0
    if not groups:
        print("no matches")
        return 0
    _print_table(
        ("NAME", "COUNTRY", "UNLOCODE", "SOURCES", "COORD", "ID"),
        [
            (
                group.name,
                group.country_code,
                group.unlocode or "-",
                ",".join(source_short_label(source) for source in group.sources),
                _group_coordinate_cell(group),
                group.best_id,
            )
            for group in groups
        ],
    )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    port = registry.resolve(args.port, country_code=args.country_code)
    if args.json:
        _print_json(port.to_dict())
        return 0
    for line in _port_lines(port):
        print(line)
    return 0


def _cmd_near(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    if args.all_sources:
        results = registry.nearest(
            args.latitude,
            args.longitude,
            country_code=args.country_code,
            limit=args.limit,
            max_distance_nmi=args.max_distance_nmi,
        )
        if args.json:
            _print_json([result.to_dict() for result in results])
            return 0
        if not results:
            print("no matches")
            return 0
        _print_table(
            ("NAME", "COUNTRY", "PROVIDER", "DISTANCE_NMI", "ID"),
            [
                (
                    result.port.name,
                    result.port.country_code,
                    result.port.provider,
                    f"{result.distance_nmi:.2f}",
                    result.port.registry_id,
                )
                for result in results
            ],
        )
        return 0

    groups = registry.nearest_grouped(
        args.latitude,
        args.longitude,
        country_code=args.country_code,
        limit=args.limit,
        max_distance_nmi=args.max_distance_nmi,
    )
    if args.json:
        _print_json([result.to_dict() for result in groups])
        return 0
    if not groups:
        print("no matches")
        return 0
    _print_table(
        ("NAME", "COUNTRY", "UNLOCODE", "SOURCES", "DISTANCE_NMI", "ID"),
        [
            (
                result.group.name,
                result.group.country_code,
                result.group.unlocode or "-",
                ",".join(source_short_label(s) for s in result.group.sources),
                f"{result.distance_nmi:.2f}",
                result.group.best_id,
            )
            for result in groups
        ],
    )
    return 0


def _cmd_route(args: argparse.Namespace) -> int:
    from sea_mile.router import SeaRouter

    registry = _load_registry(args)
    origin = _endpoint_port(registry, args.origin, args.origin_country)
    destination = _endpoint_port(registry, args.destination, args.destination_country)
    try:
        result = SeaRouter().route(origin, destination)
    except ImportError as error:
        print(f"sea-mile: error: {error}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(result.summary())
    else:
        detour = (
            f"{result.detour_ratio:.3f}" if result.detour_ratio is not None else "-"
        )
        print(f"origin: {origin.name} ({origin.registry_id})")
        print(f"destination: {destination.name} ({destination.registry_id})")
        print(f"distance_nmi: {result.distance_nmi:.2f}")
        print(f"great_circle_nmi: {result.great_circle_nmi:.2f}")
        print(f"detour_ratio: {detour}")
        print(f"quality_flag: {result.quality_flag}")
        print(
            f"engine: {result.engine} {result.engine_version} "
            f"({result.algorithm}, {result.backend})"
        )
    if args.geojson:
        args.geojson.parent.mkdir(parents=True, exist_ok=True)
        args.geojson.write_text(
            json.dumps(result.to_geojson_feature(), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        if not args.json:
            print(f"geojson: {args.geojson}")
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    from sea_mile.router import SeaRouter

    registry = _load_registry(args)
    ports = [registry.resolve(identifier) for identifier in args.ports]
    try:
        matrix = SeaRouter().distance_matrix(ports)
    except ImportError as error:
        print(f"sea-mile: error: {error}", file=sys.stderr)
        return 2
    labels = [port.registry_id for port in ports]
    if args.json:
        _print_json({"ports": labels, "distances_nmi": matrix})
        return 0
    _print_table(
        ("FROM/TO", *labels),
        [
            (label, *[f"{distance:.1f}" for distance in row])
            for label, row in zip(labels, matrix, strict=True)
        ],
    )
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    if args.query:
        results = registry.search(
            args.query, country_code=args.country_code, limit=args.limit
        )
        ports: list[Port] = [result.port for result in results]
    elif args.country_code:
        ports = registry.ports_in_country(args.country_code)
    else:
        raise ValueError("export needs --query or --country")

    if args.format == "geojson":
        payload = {
            "type": "FeatureCollection",
            "features": [port.to_geojson_feature() for port in ports],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = _ports_to_csv(ports)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {len(ports)} records to {args.output}")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_match(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    with args.input.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if args.name_column not in fieldnames:
            raise ValueError(
                f"input has no column {args.name_column!r}; "
                f"columns are {', '.join(fieldnames) or 'none'}"
            )
        if args.country_column and args.country_column not in fieldnames:
            raise ValueError(f"input has no column {args.country_column!r}")
        rows = list(reader)

    names = [str(row.get(args.name_column) or "").strip() for row in rows]
    country_codes: list[str | None] | None = None
    if args.country_column:
        country_codes = [
            (str(row.get(args.country_column) or "").strip() or None) for row in rows
        ]
    results = registry.match_names(names, country_codes=country_codes)

    if args.json:
        _print_json([result.to_dict() for result in results])
        return 0
    if not results:
        print("no rows")
        return 0
    _print_table(
        ("INPUT", "COUNTRY", "STATUS", "TIER", "SELECTED_ID", "REASON"),
        [
            (
                result.query,
                result.country_code or "-",
                str(result.status),
                str(result.confidence_tier),
                result.selected_registry_id or "-",
                result.reason,
            )
            for result in results
        ],
    )
    return 0


def _cmd_tui(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    try:
        from sea_mile import tui
    except ImportError:
        print(
            "sea-mile: error: the tui command needs the 'tui' extra "
            "(pip install 'sea-mile[tui]' or uv sync --extra tui)",
            file=sys.stderr,
        )
        return 2
    tui.run(registry)
    return 0


def _print_download_manifest(manifest: dict[str, Any]) -> None:
    print(f"retrieved_at_utc: {manifest['retrieved_at_utc']}")
    for source, details in manifest["sources"].items():
        print(f"{source}: {details['path']} ({details['bytes']:,} bytes)")


def _print_build_manifest(manifest: dict[str, Any]) -> None:
    print(f"registry_rows: {manifest['registry_rows']}")
    print(f"alias_rows: {manifest['alias_rows']}")
    for provider, counts in manifest["providers"].items():
        print(
            f"provider {provider}: {counts['records']} records, "
            f"{counts['records_with_coordinates']} with coordinates, "
            f"{counts['aliases']} aliases"
        )
    print(
        "duplicate_provider_ids_reconciled: "
        f"{manifest['duplicate_provider_ids_reconciled']}"
    )
    print(f"coordinate_conflict_records: {manifest['coordinate_conflict_records']}")


def _print_verify_report(report: dict[str, Any]) -> None:
    print(f"status: {report['status']}")
    for check in report["checks"]:
        mark = "ok" if check["passed"] else "FAIL"
        print(f"[{mark}] {check['name']}: {check['detail']}")
    route = report["route_check"]
    if "skipped" in route:
        print(f"route_check: skipped ({route['skipped']})")


def _cmd_data(args: argparse.Namespace) -> int:
    if args.data_command == "verify":
        from sea_mile.validation import verify_reference_data

        report = verify_reference_data(args.reference_root)
        if args.json:
            _print_json(report)
        else:
            _print_verify_report(report)
        return 0 if report["status"] == "passed" else 1
    if args.data_command in {"download", "prepare"}:
        from sea_mile.source_data import download_reference_data

        download_manifest = download_reference_data(
            args.reference_root, refresh=getattr(args, "refresh", False)
        )
        if args.json:
            _print_json(download_manifest)
        else:
            _print_download_manifest(download_manifest)
    if args.data_command in {"build", "prepare"}:
        from sea_mile.registry_build import build_reference_registry

        build_manifest = build_reference_registry(args.reference_root)
        if args.json:
            _print_json(build_manifest)
        else:
            _print_build_manifest(build_manifest)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sea-mile",
        description=(
            "Search a local port registry and calculate approximate sea routes."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="directory containing port_registry.parquet and port_aliases.parquet",
    )
    parser.add_argument("--version", action="version", version=f"sea-mile {_version()}")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log progress to stderr",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON instead of readable text",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser(
        "info", parents=[common], help="show registry size and provider coverage"
    )
    info.set_defaults(func=_cmd_info)

    tui = subparsers.add_parser(
        "tui",
        parents=[common],
        help="launch an interactive terminal port search (needs the tui extra)",
    )
    tui.set_defaults(func=_cmd_tui)

    search = subparsers.add_parser(
        "search", parents=[common], help="search port names and aliases"
    )
    search.add_argument("query")
    search.add_argument("--country", dest="country_code")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--minimum-score", type=float, default=75.0)
    search.add_argument(
        "--exact-only", action="store_true", help="disable fuzzy alias matching"
    )
    search.add_argument(
        "--all-sources",
        action="store_true",
        help="show one row per source record instead of grouped ports",
    )
    search.set_defaults(func=_cmd_search)

    match_cmd = subparsers.add_parser(
        "match",
        parents=[common],
        help="resolve a CSV of port names in bulk",
    )
    match_cmd.add_argument("input", type=Path, help="CSV file with a name column")
    match_cmd.add_argument(
        "--name-column", default="name", help="column holding the port name"
    )
    match_cmd.add_argument(
        "--country-column", help="optional column holding a two-letter country code"
    )
    match_cmd.set_defaults(func=_cmd_match)

    show = subparsers.add_parser(
        "show", parents=[common], help="show one port by registry ID or UN/LOCODE"
    )
    show.add_argument("port")
    show.add_argument("--country", dest="country_code")
    show.set_defaults(func=_cmd_show)

    near = subparsers.add_parser(
        "near",
        parents=[common],
        help="find source-aware port records nearest to a coordinate",
    )
    near.add_argument("latitude", type=float)
    near.add_argument("longitude", type=float)
    near.add_argument("--country", dest="country_code")
    near.add_argument("--limit", type=int, default=10)
    near.add_argument("--max-distance-nmi", type=float)
    near.add_argument(
        "--all-sources",
        action="store_true",
        help="show one row per source record instead of grouped ports",
    )
    near.set_defaults(func=_cmd_near)

    route = subparsers.add_parser(
        "route",
        parents=[common],
        help="calculate an approximate route between two ports",
    )
    route.add_argument("origin", help="port ID, UN/LOCODE, or a lat,lon coordinate")
    route.add_argument(
        "destination", help="port ID, UN/LOCODE, or a lat,lon coordinate"
    )
    route.add_argument("--origin-country")
    route.add_argument("--destination-country")
    route.add_argument(
        "--geojson", type=Path, help="write the route as a GeoJSON Feature"
    )
    route.set_defaults(func=_cmd_route)

    matrix = subparsers.add_parser(
        "matrix",
        parents=[common],
        help="pairwise sea distances between two or more ports",
    )
    matrix.add_argument("ports", nargs="+", help="two or more port IDs or UN/LOCODEs")
    matrix.set_defaults(func=_cmd_matrix)

    export = subparsers.add_parser(
        "export", parents=[common], help="export matching port records"
    )
    export.add_argument("--query", help="port name to search for")
    export.add_argument("--country", dest="country_code")
    export.add_argument("--limit", type=int, default=1000)
    export.add_argument(
        "--format", choices=("csv", "geojson"), default="csv", help="output format"
    )
    export.add_argument(
        "--output", type=Path, help="write to this file instead of stdout"
    )
    export.set_defaults(func=_cmd_export)

    data = subparsers.add_parser(
        "data", help="download public sources or build the local registry"
    )
    data_subparsers = data.add_subparsers(dest="data_command", required=True)
    for command, help_text in (
        ("download", "download versioned public source snapshots"),
        ("build", "build Parquet registry files from local snapshots"),
        ("prepare", "download sources and then build the registry"),
        ("verify", "check a local build against its manifests and rules"),
    ):
        data_command = data_subparsers.add_parser(
            command, parents=[common], help=help_text
        )
        data_command.add_argument(
            "--reference-root",
            type=Path,
            default=None,
            help="root directory for raw snapshots, manifests, and processed data",
        )
        if command in {"download", "prepare"}:
            data_command.add_argument(
                "--refresh",
                action="store_true",
                help="redownload sources even when a local snapshot already exists",
            )
        data_command.set_defaults(func=_cmd_data)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process-compatible status code."""

    args = _parser().parse_args(argv)
    if args.data_dir is None:
        args.data_dir = _default_data_directory()
    if hasattr(args, "reference_root") and args.reference_root is None:
        args.reference_root = _default_reference_root()
    if getattr(args, "verbose", False):
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
        )
    try:
        return args.func(args)
    except (SeaMileError, ValueError) as error:
        print(f"sea-mile: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
