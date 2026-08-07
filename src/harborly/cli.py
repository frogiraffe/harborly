"""Command-line interface for the public port registry and sea router."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import html
import io
import json
import logging
import math
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from harborly.exceptions import HarborlyError, SourceDataError
from harborly.matching import BatchMatchResult, MatchReason, MatchStatus
from harborly.ports import (
    _ENRICHMENT_FIELDS,
    Port,
    PortGroup,
    PortRegistry,
    _result_enrichment,
    bundled_data_directory,
    source_short_label,
)
from harborly.routing import PassageRestriction

logger = logging.getLogger("harborly")

if TYPE_CHECKING:
    from harborly.router import SeaRoute

_PORT_FIELDS = [field.name for field in dataclasses.fields(Port)]


def _version() -> str:
    try:
        return version("harborly")
    except PackageNotFoundError:
        return "0.0.0"


def _module_available(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (AttributeError, ImportError, ValueError):
        return False


def _print_optional_extras_error(feature: str, extras: Sequence[str]) -> None:
    unique_extras = list(dict.fromkeys(extras))
    extras_spec = ",".join(unique_extras)
    sync_flags = " ".join(f"--extra {extra}" for extra in unique_extras)
    labels = " and ".join(f"'{extra}'" for extra in unique_extras)
    print(
        f"harborly: error: {feature} needs the {labels} extras\n"
        "install every required extra in the same environment:\n"
        f"  uv tool:        uv tool install --force 'harborly[{extras_spec}]'\n"
        f"  virtualenv:     python -m pip install 'harborly[{extras_spec}]'\n"
        f"  source checkout: uv sync {sync_flags}\n"
        "                   then run the command with 'uv run harborly'",
        file=sys.stderr,
    )


def _require_optional_extras(
    feature: str, requirements: Sequence[tuple[str, str]]
) -> bool:
    if all(_module_available(module) for _, module in requirements):
        return True
    _print_optional_extras_error(feature, [extra for extra, _ in requirements])
    return False


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
    from harborly.router import _coordinate_port

    return _coordinate_port(value, coordinate[0], coordinate[1])


def _route_export_temp_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    return Path(path)


def _remove_route_export_files(paths: Sequence[Path]) -> None:
    for path in paths:
        with suppress(OSError):
            path.unlink(missing_ok=True)


def _validate_route_output_paths(paths: Sequence[Path | None]) -> None:
    targets = [path.resolve(strict=False) for path in paths if path is not None]
    if len(targets) != len(set(targets)):
        raise ValueError("route output paths must be distinct")


def _write_route_exports(
    exports: Sequence[tuple[str, Path, Callable[[Path], None]]],
) -> None:
    staged: list[tuple[str, Path, Path]] = []
    backups: list[tuple[Path, Path]] = []
    original_targets: set[Path] = set()
    published_targets: set[Path] = set()
    label = "route export"
    target = Path()
    try:
        for label, target, write_export in exports:
            temporary = _route_export_temp_path(target)
            staged.append((label, target, temporary))
            write_export(temporary)

        for export_label, target, _ in staged:
            label = export_label
            if target.exists():
                backup = _route_export_temp_path(target)
                try:
                    target.replace(backup)
                except OSError:
                    _remove_route_export_files([backup])
                    raise
                backups.append((target, backup))
                original_targets.add(target)

        for export_label, target, temporary in staged:
            label = export_label
            temporary.replace(target)
            published_targets.add(target)
    except OSError as error:
        for original, backup in reversed(backups):
            with suppress(OSError):
                backup.replace(original)
        _remove_route_export_files(
            [temporary for _, _, temporary in staged]
            + [target for target in published_targets if target not in original_targets]
        )
        raise ValueError(f"could not write {label} to {target}: {error}") from error
    except Exception:
        _remove_route_export_files([temporary for _, _, temporary in staged])
        raise
    else:
        _remove_route_export_files([backup for _, backup in backups])


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
    return bundled_data_directory()


def _coordinate(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a coordinate. 'near' takes a latitude and "
            "longitude, not a port name: resolve one first with "
            "'harborly search' or 'harborly show', then pass its coordinate."
        ) from None


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid port") from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a port in the range 0-65535"
        )
    return port


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a positive integer"
        ) from None
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a positive number"
        ) from None
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} is not a positive number")
    return parsed


def _default_reference_root() -> Path:
    project_reference = Path.cwd() / "data" / "reference"
    if project_reference.exists():
        return project_reference
    return Path.home() / ".local" / "share" / "harborly" / "reference"


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


OUTPUT_SCHEMA_VERSION = "1"


def _command_label(args: argparse.Namespace) -> str:
    if args.command in {"cache", "data"}:
        return f"{args.command} {getattr(args, f'{args.command}_command')}"
    return str(args.command)


def _emit_json(
    args: argparse.Namespace, data: object, *, warnings: list[str] | None = None
) -> None:
    """Serialize one command result using the current output schema."""

    _print_json(
        {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "command": _command_label(args),
            "data": data,
            "warnings": warnings or [],
        }
    )


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else "usage_error"


def _error_details(error: Exception) -> dict[str, str]:
    reason = getattr(error, "reason", None)
    return {"reason": str(reason)} if reason is not None else {}


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
        f"canonical_id: {port.canonical_id}",
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
        _emit_json(
            args,
            {
                "registry_records": len(registry),
                "providers": registry.providers,
                "data_directory": data_directory,
            },
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
            _emit_json(args, [result.to_dict() for result in results])
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
        _emit_json(args, [group.to_dict() for group in groups])
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
        _emit_json(args, port.to_dict())
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
            _emit_json(args, [result.to_dict() for result in results])
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
        _emit_json(args, [result.to_dict() for result in groups])
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
    from harborly.router import SeaRouter, SequenceSeaRoute

    if args.via and args.html_map:
        raise ValueError("route --via cannot be combined with --html-map")
    _validate_route_output_paths((args.geojson, args.kml, args.html_map))

    requirements = [("routing", "searoute")]
    if args.html_map:
        requirements.append(("map", "folium"))
    if not _require_optional_extras(
        "route --html-map" if args.html_map else "route", requirements
    ):
        return 2

    html_map_writer: Callable[[SeaRoute, Path], None] | None = None
    if args.html_map:
        try:
            from harborly.html_map import write_route_html
        except ImportError:
            _print_optional_extras_error(
                "route --html-map", [extra for extra, _ in requirements]
            )
            return 2
        html_map_writer = write_route_html

    registry = _load_registry(args)
    origin = _endpoint_port(registry, args.origin, args.origin_country)
    via_ports = [_endpoint_port(registry, value, None) for value in args.via]
    destination = _endpoint_port(registry, args.destination, args.destination_country)
    try:
        result: SeaRoute | SequenceSeaRoute
        route_kwargs = {}
        if args.speed_knots is not None:
            route_kwargs["speed_knots"] = args.speed_knots
        router_kwargs = {"cache_path": args.cache}
        if args.restrictions is not None:
            router_kwargs["restrictions"] = args.restrictions
        router = SeaRouter(**router_kwargs)
        if via_ports:
            result = router.route_sequence(
                [origin, *via_ports, destination], **route_kwargs
            )
        else:
            result = router.route(origin, destination, **route_kwargs)
    except ImportError:
        _print_optional_extras_error(
            "route --html-map" if args.html_map else "route",
            [extra for extra, _ in requirements],
        )
        return 2
    route_exports: list[tuple[str, Path, Callable[[Path], None]]] = []
    if args.geojson:
        geojson = (
            result.to_geojson_feature_collection()
            if isinstance(result, SequenceSeaRoute)
            else result.to_geojson_feature()
        )
        geojson_text = json.dumps(geojson, ensure_ascii=False, indent=2) + "\n"

        def write_geojson(path: Path) -> None:
            path.write_text(geojson_text, encoding="utf-8")

        route_exports.append(("GeoJSON", args.geojson, write_geojson))
    if args.kml:
        route_exports.append(("KML", args.kml, result.write_kml))
    _write_route_exports(route_exports)
    if args.html_map and html_map_writer is not None:
        assert not isinstance(result, SequenceSeaRoute)
        try:
            html_map_writer(result, args.html_map)
        except OSError as error:
            raise ValueError(
                f"could not write HTML map to {args.html_map}: {error}"
            ) from error
    if args.json:
        _emit_json(args, result.summary())
    elif isinstance(result, SequenceSeaRoute):
        for index, leg in enumerate(result.legs, start=1):
            print(
                f"leg {index}: {leg.origin.name} ({leg.origin.registry_id}) -> "
                f"{leg.destination.name} ({leg.destination.registry_id})"
            )
            print(f"  distance_nmi: {leg.distance_nmi:.2f}")
        print(f"total_distance_nmi: {result.total_distance_nmi:.2f}")
        if result.duration_hours is not None:
            print(f"duration_hours: {result.duration_hours:.2f}")
            print(f"duration_days: {result.duration_days:.2f}")
        if args.geojson:
            print(f"geojson: {args.geojson}")
        if args.kml:
            print(f"kml: {args.kml}")
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
        if result.speed_knots is not None:
            print(f"speed_knots: {result.speed_knots:.1f}")
            print(f"duration_hours: {result.duration_hours:.2f}")
            print(f"duration_days: {result.duration_days:.2f}")
        print(
            f"engine: {result.engine} {result.engine_version} "
            f"({result.algorithm}, {result.backend})"
        )
        if args.geojson:
            print(f"geojson: {args.geojson}")
        if args.kml:
            print(f"kml: {args.kml}")
        if args.html_map:
            print(f"html_map: {args.html_map}")
            print(
                "html_map_note: direct file viewing uses an embedded coastline; "
                "serve the output directory over localhost for detailed map tiles"
            )
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    if len(args.ports) < 2:
        raise ValueError("matrix needs two or more ports")
    from harborly.router import SeaRouter

    registry = _load_registry(args)
    ports = [registry.resolve(identifier) for identifier in args.ports]
    labels = [port.registry_id for port in ports]
    router = SeaRouter(cache_path=args.cache)
    try:
        if args.edge_csv:
            if args.json:
                raise ValueError("matrix --edge-csv cannot be combined with --json")
            args.edge_csv.parent.mkdir(parents=True, exist_ok=True)
            partial = args.edge_csv.with_suffix(args.edge_csv.suffix + ".part")
            partial.unlink(missing_ok=True)
            count = 0
            try:
                with partial.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(("origin", "destination", "distance_nmi"))
                    for row, column, distance in router.iter_distance_edges(
                        ports, max_workers=args.workers
                    ):
                        writer.writerow((labels[row], labels[column], distance))
                        count += 1
                partial.replace(args.edge_csv)
            except Exception:
                partial.unlink(missing_ok=True)
                raise
            print(f"wrote {count} route edges to {args.edge_csv}")
            return 0
        matrix = router.distance_matrix(ports, max_workers=args.workers)
    except ImportError as error:
        print(f"harborly: error: {error}", file=sys.stderr)
        return 2
    from harborly.data_contracts import validate_distance_matrix

    validate_distance_matrix(labels, matrix)
    if args.json:
        _emit_json(args, {"ports": labels, "distances_nmi": matrix})
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
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"wrote {len(ports)} records to {args.output}")
        else:
            sys.stdout.write(text)
    elif args.format == "kml":
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2">',
            "  <Document>",
            f"    <name>Ports Export ({len(ports)} records)</name>",
        ]
        for port in ports:
            if port.latitude is not None and port.longitude is not None:
                lines.extend(
                    [
                        "    <Placemark>",
                        f"      <name>{html.escape(port.name)}</name>",
                        (
                            f"      <description>{html.escape(port.registry_id)} "
                            f"({html.escape(port.country_code or '')})</description>"
                        ),
                        "      <Point>",
                        (
                            "        <coordinates>"
                            f"{port.longitude},{port.latitude},0"
                            "</coordinates>"
                        ),
                        "      </Point>",
                        "    </Placemark>",
                    ]
                )
        lines.extend(["  </Document>", "</kml>"])
        text = "\n".join(lines) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"wrote {len(ports)} records to {args.output}")
        else:
            sys.stdout.write(text)
    elif args.format == "geoparquet":
        if not args.output:
            raise ValueError(
                "export format 'geoparquet' requires an --output file path"
            )
        from harborly.geoparquet import write_ports_geoparquet

        write_ports_geoparquet(ports, args.output)
        print(f"wrote {len(ports)} records to {args.output}")
    else:
        text = _ports_to_csv(ports)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"wrote {len(ports)} records to {args.output}")
        else:
            sys.stdout.write(text)
    return 0


_MATCH_CHUNK_SIZE = 10_000

_REVIEW_FIELDS = [
    "row_id",
    "input_name",
    "input_country",
    "status",
    "reason_code",
    "candidate_registry_id",
    "candidate_provider",
    "candidate_name",
    "candidate_country_code",
    "candidate_latitude",
    "candidate_longitude",
    "candidate_unlocode",
    "candidate_match_method",
    "candidate_name_score",
]

_REVIEW_STATUSES = frozenset({MatchStatus.REVIEW_REQUIRED, MatchStatus.UNRESOLVED})


def _match_row_ids(
    rows: Sequence[dict[str, Any]], id_column: str | None, offset: int = 0
) -> list[str]:
    if id_column:
        return [str(row.get(id_column) or "").strip() for row in rows]
    return [str(offset + index + 1) for index in range(len(rows))]


def _validate_input_ids(path: Path, id_column: str) -> None:
    """Reject missing or duplicate explicit row IDs before output files open."""

    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if id_column not in fields:
            raise ValueError(
                f"input has no column {id_column!r}; "
                f"columns are {', '.join(fields) or 'none'}"
            )
        for line_number, row in enumerate(reader, start=2):
            row_id = str(row.get(id_column) or "").strip()
            if not row_id:
                raise ValueError(f"input row {line_number} has an empty {id_column!r}")
            if row_id in seen:
                raise ValueError(
                    f"input row {line_number} repeats {id_column!r} value {row_id!r}"
                )
            seen.add(row_id)


def _chunked(
    rows: Iterator[dict[str, Any]], size: int
) -> Iterator[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _read_decisions(path: Path) -> dict[str, str]:
    import pandas as pd
    import pandera.errors

    from harborly.data_contracts import validate_review_decisions

    frame = pd.read_csv(
        path,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    for column in frame.columns:
        frame[column] = frame[column].str.strip()
    try:
        validated = validate_review_decisions(frame)
    except (pandera.errors.SchemaError, pandera.errors.SchemaErrors) as error:
        raise ValueError(f"invalid review decisions CSV: {error}") from error
    return dict(
        zip(
            validated["row_id"].str.strip(),
            validated["chosen_registry_id"].str.strip(),
            strict=True,
        )
    )


def _apply_decision(
    result: BatchMatchResult,
    row_id: str,
    decisions: dict[str, str],
) -> BatchMatchResult:
    chosen = decisions.get(row_id)
    if chosen is None:
        return result
    return dataclasses.replace(
        result,
        status=MatchStatus.MANUALLY_RESOLVED,
        selected_registry_id=chosen,
        reason_code=MatchReason.MANUAL_DECISION,
        reason="resolved from the decisions file",
        rules_applied=(*result.rules_applied, "manual_decision"),
    )


class _EnrichedWriter:
    def __init__(self, path: Path, input_fieldnames: Sequence[str]) -> None:
        self._fieldnames = list(input_fieldnames) + [
            field for field in _ENRICHMENT_FIELDS if field not in input_fieldnames
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=self._fieldnames)
        self._writer.writeheader()

    def write(
        self,
        rows: Sequence[dict[str, Any]],
        results: Sequence[BatchMatchResult],
        registry: PortRegistry,
    ) -> None:
        for row, result in zip(rows, results, strict=True):
            self._writer.writerow({**row, **_result_enrichment(registry, result)})

    def close(self) -> None:
        self._handle.close()


class _ReviewWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=_REVIEW_FIELDS)
        self._writer.writeheader()

    def write(
        self, row_ids: Sequence[str], results: Sequence[BatchMatchResult]
    ) -> None:
        pending: list[dict[str, Any]] = []
        for row_id, result in zip(row_ids, results, strict=True):
            if result.status not in _REVIEW_STATUSES:
                continue
            base = {
                "row_id": row_id,
                "input_name": result.query,
                "input_country": result.country_code or "",
                "status": str(result.status),
                "reason_code": str(result.reason_code),
            }
            if not result.candidates:
                pending.append(base)
                continue
            for candidate in result.candidates:
                pending.append(
                    {
                        **base,
                        "candidate_registry_id": candidate.registry_id,
                        "candidate_provider": candidate.provider,
                        "candidate_name": candidate.name,
                        "candidate_country_code": candidate.country_code,
                        "candidate_latitude": (
                            candidate.latitude if candidate.latitude is not None else ""
                        ),
                        "candidate_longitude": (
                            candidate.longitude
                            if candidate.longitude is not None
                            else ""
                        ),
                        "candidate_unlocode": candidate.unlocode or "",
                        "candidate_match_method": candidate.match_method,
                        "candidate_name_score": candidate.name_score,
                    }
                )
        if not pending:
            return
        import pandas as pd

        from harborly.data_contracts import validate_review_frame

        frame = pd.DataFrame(pending, columns=_REVIEW_FIELDS)
        for column in ("candidate_latitude", "candidate_longitude"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        validated = validate_review_frame(frame)
        for row in validated.fillna("").to_dict("records"):
            self._writer.writerow(row)

    def close(self) -> None:
        self._handle.close()


def _print_stream_summary(
    args: argparse.Namespace, total: int, counts: Counter[str]
) -> None:
    if args.output:
        print(f"wrote {total} rows to {args.output}")
    if args.review:
        review = counts[str(MatchStatus.REVIEW_REQUIRED)]
        review += counts[str(MatchStatus.UNRESOLVED)]
        print(f"wrote {review} rows needing review to {args.review}")
    print(", ".join(f"{status}: {count}" for status, count in sorted(counts.items())))


def _cmd_match(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    if args.id_column:
        _validate_input_ids(args.input, args.id_column)
    decisions = _read_decisions(args.decisions) if args.decisions else None
    if decisions is not None:
        for row_id, chosen in decisions.items():
            if chosen not in registry:
                raise ValueError(
                    f"decision for row {row_id!r} names unknown registry ID {chosen!r}"
                )
    hold_results = bool(args.json) or not (args.output or args.review)

    collected: list[BatchMatchResult] = []
    counts: Counter[str] = Counter()
    total = 0

    with args.input.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        for column in (args.name_column, args.country_column, args.id_column):
            if column and column not in fieldnames:
                raise ValueError(
                    f"input has no column {column!r}; "
                    f"columns are {', '.join(fieldnames) or 'none'}"
                )

        enriched = _EnrichedWriter(args.output, fieldnames) if args.output else None
        review = _ReviewWriter(args.review) if args.review else None
        try:
            offset = 0
            for chunk in _chunked(reader, _MATCH_CHUNK_SIZE):
                names = [str(row.get(args.name_column) or "").strip() for row in chunk]
                country_codes: list[str | None] | None = None
                if args.country_column:
                    country_codes = [
                        (str(row.get(args.country_column) or "").strip() or None)
                        for row in chunk
                    ]
                results = registry.match_names(names, country_codes=country_codes)
                row_ids = _match_row_ids(chunk, args.id_column, offset)
                offset += len(chunk)
                if decisions is not None:
                    results = [
                        _apply_decision(result, row_id, decisions)
                        for result, row_id in zip(results, row_ids, strict=True)
                    ]
                if enriched is not None:
                    enriched.write(chunk, results, registry)
                if review is not None:
                    review.write(row_ids, results)
                for result in results:
                    counts[str(result.status)] += 1
                total += len(results)
                if hold_results:
                    collected.extend(results)
        finally:
            if enriched is not None:
                enriched.close()
            if review is not None:
                review.close()

    if args.json:
        _emit_json(args, [result.to_dict() for result in collected])
        return 0
    if args.output or args.review:
        _print_stream_summary(args, total, counts)
        return 0
    if not collected:
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
            for result in collected
        ],
    )
    return 0


def _cmd_tui(args: argparse.Namespace) -> int:
    requirements = [("tui", "textual")]
    if not _require_optional_extras("tui", requirements):
        return 2
    registry = _load_registry(args)
    try:
        from harborly import tui
    except ImportError:
        _print_optional_extras_error("tui", ["tui"])
        return 2
    tui.run(registry)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    requirements = [
        ("api", "fastapi"),
        ("api", "uvicorn"),
        ("routing", "searoute"),
    ]
    if not _require_optional_extras("serve", requirements):
        return 2
    try:
        from harborly.api import run_server
    except ImportError:
        _print_optional_extras_error("serve", ["api", "routing"])
        return 2
    run_server(host=args.host, port=args.port)
    return 0


def _print_download_manifest(manifest: dict[str, Any]) -> None:
    print(f"retrieved_at_utc: {manifest['retrieved_at_utc']}")
    for source, details in manifest["sources"].items():
        print(f"{source}: {details['path']} ({details['bytes']:,} bytes)")


def _print_build_manifest(manifest: dict[str, Any]) -> None:
    print(f"registry_schema_version: {manifest['registry_schema_version']}")
    print(f"registry_content_hash: {manifest['registry_content_hash']}")
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


def _print_source_lock(lock: dict[str, Any]) -> None:
    print(f"lock_version: {lock['lock_version']}")
    print(f"generated_at_utc: {lock['generated_at_utc']}")
    for source, details in lock.get("sources", {}).items():
        label = details.get("snapshot_label") or details.get("release") or "-"
        digest = str(details.get("sha256", ""))[:12]
        print(f"{source}: {label} sha256={digest}")


def _print_verify_report(report: dict[str, Any]) -> None:
    print(f"data_source: {report['data_source']}")
    print(f"reference_root: {report['reference_root']}")
    print(f"status: {report['status']}")
    for check in report["checks"]:
        mark = "ok" if check["passed"] else "FAIL"
        print(f"[{mark}] {check['name']}: {check['detail']}")
    route = report["route_check"]
    if "skipped" in route:
        print(f"route_check: skipped ({route['skipped']})")


def _cmd_data(args: argparse.Namespace) -> int:
    if args.data_command == "verify":
        from harborly.validation import verify_reference_data

        report = verify_reference_data(args.reference_root)
        if args.json:
            _emit_json(args, report)
        else:
            _print_verify_report(report)
        return 0 if report["status"] == "passed" else 1
    if args.data_command == "lock":
        from harborly.build.download import write_source_lock

        lock = write_source_lock(args.reference_root, lock_path=args.output)
        if args.json:
            _emit_json(args, lock)
        else:
            _print_source_lock(lock)
        return 0
    payload: dict[str, Any] = {}
    if args.data_command in {"download", "prepare"}:
        from harborly.build.download import download_reference_data

        download_manifest = download_reference_data(
            args.reference_root, refresh=getattr(args, "refresh", False)
        )
        payload["download"] = download_manifest
        if not args.json:
            _print_download_manifest(download_manifest)
    if args.data_command in {"build", "prepare"}:
        if getattr(args, "lock", None) is not None:
            from harborly.build.download import load_source_lock, lock_mismatches

            mismatches = lock_mismatches(
                args.reference_root, load_source_lock(args.lock)
            )
            if mismatches:
                raise SourceDataError("source lock mismatch: " + ", ".join(mismatches))
        from harborly.build.registry import build_reference_registry

        build_manifest = build_reference_registry(args.reference_root)
        payload["build"] = build_manifest
        if not args.json:
            _print_build_manifest(build_manifest)
    if args.json:
        _emit_json(
            args,
            payload if args.data_command == "prepare" else payload[args.data_command],
        )
    return 0


def _cmd_cache(args: argparse.Namespace) -> int:
    from harborly.route_cache import RouteCache

    if not args.path.is_file():
        raise ValueError(f"route cache does not exist: {args.path}")
    cache = RouteCache(args.path)
    removed = 0
    if args.cache_command == "prune":
        removed = cache.prune(older_than_days=args.older_than_days)
    elif args.cache_command == "clear":
        removed = cache.clear()
    if getattr(args, "vacuum", False):
        cache.vacuum()

    payload = cache.info().to_dict()
    payload["operation"] = args.cache_command
    if args.cache_command != "info":
        payload["removed_entries"] = removed
        payload["vacuumed"] = bool(args.vacuum)

    if args.json:
        _emit_json(args, payload)
        return 0

    print(f"path: {payload['path']}")
    print(f"schema_version: {payload['schema_version']}")
    print(f"entries: {payload['entries']}")
    print(f"oldest_created_at: {payload['oldest_created_at'] or '-'}")
    print(f"newest_created_at: {payload['newest_created_at'] or '-'}")
    print(f"database_bytes: {payload['database_bytes']}")
    print(f"wal_bytes: {payload['wal_bytes']}")
    if args.cache_command != "info":
        print(f"removed_entries: {removed}")
        print(f"vacuumed: {'yes' if args.vacuum else 'no'}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harborly",
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
    parser.add_argument("--version", action="version", version=f"harborly {_version()}")
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
        help="print JSON instead of text output",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser(
        "info", parents=[common], help="show registry size and provider coverage"
    )
    info.set_defaults(func=_cmd_info)

    tui = subparsers.add_parser(
        "tui",
        help="launch an interactive terminal port map (needs the tui extra)",
    )
    tui.set_defaults(func=_cmd_tui)

    serve = subparsers.add_parser(
        "serve",
        help="serve bundled port routes over HTTP (needs the api and routing extras)",
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=_port, default=8000)
    serve.set_defaults(func=_cmd_serve)

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
    match_cmd.add_argument(
        "--id-column", help="column holding a stable row id used for review decisions"
    )
    match_cmd.add_argument(
        "--output",
        type=Path,
        help="write the input rows plus harborly_* columns to this CSV",
    )
    match_cmd.add_argument(
        "--review",
        type=Path,
        help="write rows needing review to this CSV, one row per candidate",
    )
    match_cmd.add_argument(
        "--decisions",
        type=Path,
        help="apply a decisions CSV with row_id and chosen_registry_id columns",
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
    near.add_argument("latitude", type=_coordinate)
    near.add_argument("longitude", type=_coordinate)
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
    route.add_argument("--via", action="append", default=[], help="intermediate port")
    route.add_argument(
        "--restrictions",
        nargs="+",
        choices=tuple(str(value) for value in PassageRestriction),
        help="passages to avoid",
    )
    route.add_argument(
        "--geojson", type=Path, help="write the route as a GeoJSON Feature"
    )
    route.add_argument("--kml", type=Path, help="write the route as a KML document")
    route.add_argument(
        "--html-map",
        type=Path,
        help="write an interactive route map (needs the map extra)",
    )
    route.add_argument(
        "--cache",
        type=Path,
        help="persist routing results in this SQLite cache",
    )
    route.add_argument(
        "--speed-knots",
        type=_positive_float,
        help="vessel speed in knots to calculate voyage duration",
    )
    route.set_defaults(func=_cmd_route)

    matrix = subparsers.add_parser(
        "matrix",
        parents=[common],
        help="pairwise sea distances between two or more ports",
    )
    matrix.add_argument("ports", nargs="+", help="two or more port IDs or UN/LOCODEs")
    matrix.add_argument(
        "--cache",
        type=Path,
        help="persist routing results in this SQLite cache",
    )
    matrix.add_argument(
        "--workers",
        type=_positive_int,
        help="routing worker processes (default: at most 4)",
    )
    matrix.add_argument(
        "--edge-csv",
        type=Path,
        help="stream unique route edges to CSV instead of building a dense matrix",
    )
    matrix.set_defaults(func=_cmd_matrix)

    cache = subparsers.add_parser(
        "cache", help="inspect or maintain a persistent SQLite route cache"
    )
    cache_subparsers = cache.add_subparsers(dest="cache_command", required=True)
    cache_info = cache_subparsers.add_parser(
        "info", parents=[common], help="show cache size and entry timestamps"
    )
    cache_info.add_argument("path", type=Path, help="SQLite route-cache path")
    cache_info.set_defaults(func=_cmd_cache)
    cache_prune = cache_subparsers.add_parser(
        "prune", parents=[common], help="delete entries older than a retention period"
    )
    cache_prune.add_argument("path", type=Path, help="SQLite route-cache path")
    cache_prune.add_argument(
        "--older-than-days",
        type=_positive_int,
        required=True,
        help="delete entries older than this many days",
    )
    cache_prune.add_argument(
        "--vacuum",
        action="store_true",
        help="reclaim free SQLite pages after deleting entries",
    )
    cache_prune.set_defaults(func=_cmd_cache)
    cache_clear = cache_subparsers.add_parser(
        "clear", parents=[common], help="delete every entry from one route cache"
    )
    cache_clear.add_argument("path", type=Path, help="SQLite route-cache path")
    cache_clear.add_argument(
        "--vacuum",
        action="store_true",
        help="reclaim free SQLite pages after deleting entries",
    )
    cache_clear.set_defaults(func=_cmd_cache)

    export = subparsers.add_parser("export", help="export matching port records")
    export.add_argument("--query", help="port name to search for")
    export.add_argument("--country", dest="country_code")
    export.add_argument("--limit", type=int, default=1000)
    export.add_argument(
        "--format",
        choices=("csv", "geojson", "kml", "geoparquet"),
        default="csv",
        help="output format",
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
        ("lock", "write a source lockfile from the current download manifest"),
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
        if command == "build":
            data_command.add_argument(
                "--lock",
                type=Path,
                help="verify raw snapshots against this lockfile before building",
            )
        if command == "lock":
            data_command.add_argument(
                "--output",
                type=Path,
                help="lockfile path (default harborly.lock.json in the reference root)",
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
        command = cast(Callable[[argparse.Namespace], int], args.func)
        return command(args)
    except KeyboardInterrupt:
        print("harborly: interrupted", file=sys.stderr)
        return 130
    except (HarborlyError, ValueError, TimeoutError) as error:
        if getattr(args, "json", False):
            _print_json(
                {
                    "schema_version": OUTPUT_SCHEMA_VERSION,
                    "command": _command_label(args),
                    "error": {
                        "code": _error_code(error),
                        "message": str(error),
                        "details": _error_details(error),
                    },
                }
            )
        else:
            print(f"harborly: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
