# Output schemas

Every command that supports `--json` writes one JSON document to standard output.
The document conforms to the schema identified by `schema_version` and contains
either `data` or `error`.

A JSON Schema for this format lives at
[`schemas/cli-output-1.schema.json`](schemas/cli-output-1.schema.json), and the test suite
validates the output of every `--json` command against it.

## Success document

```json
{
  "schema_version": "1",
  "command": "search",
  "data": [],
  "warnings": []
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Output schema version. |
| `command` | string | The command that produced the document, such as `search` or `data prepare`. |
| `data` | object or array | The command result. Its shape depends on the command. |
| `warnings` | array of string | Non-fatal notes. Empty when there are none. |

## Error document

A recoverable error replaces `data` with `error`, and the process exits 2.

```json
{
  "schema_version": "1",
  "command": "show",
  "error": {
    "code": "port_not_found",
    "message": "no exact port match for the requested identifier",
    "details": {}
  }
}
```

| Code | Raised when |
| --- | --- |
| `port_not_found` | No port matches the identifier or exact name. |
| `ambiguous_port` | More than one independent port identity matches. |
| `port_coordinate` | A selected port has no usable routing coordinate. |
| `routing_error` | The routing backend failed, returned an unusable result, or produced an implausible route. |
| `registry_data_error` | The local registry files are missing or invalid. |
| `source_data_error` | A public snapshot could not be downloaded or read. |
| `usage_error` | A bad argument or a missing filter, such as a one-port `matrix`. |

The `message` may change between releases. Clients should use `code` rather than
matching message text. The `details` object holds structured context and is empty
for most errors. A `routing_error` fills it with a stable `reason`, described below.

## Enumerated values

Some `data` fields carry a fixed set of string values.

### `match` decisions

| Field | Values |
| --- | --- |
| `status` | `auto_resolved`, `review_required`, `unresolved`, `manually_resolved` |
| `confidence_tier` | `A`, `B`, `C`, `D` |
| `reason_code` | `unique_exact_wpi`, `unique_exact_unlocode`, `coordinate_conflict`, `multiple_identities`, `no_candidate`, `manual_decision` |

A confidence tier is a similarity signal, not a calibrated probability. The `reason_code`
is stable for automated checks, while the `reason` text may change. The
`manually_resolved` status and the `manual_decision` reason appear only when the `match`
review workflow applies a decisions file.

### `route` quality flag

The `quality_flag` is a `RouteQualityFlag` value. Only these appear on a returned route.

| Value | Meaning |
| --- | --- |
| `ok` | The route passed the basic plausibility checks. |
| `high_detour_ratio` | The route is far longer than the great-circle lower bound. |
| `coincident_endpoints` | The origin and destination are the same point. |

The other `RouteQualityFlag` values describe a route that fails the plausibility check,
which raises a `routing_error` instead of returning.

### `routing_error` reason

A `routing_error` carries a stable `reason` in `details`. Programmatic error
handling must use this value rather than `message`.

| `details.reason` | Raised when |
| --- | --- |
| `backend_call_failed` | The routing backend raised while computing the route. |
| `malformed_backend_result` | The backend returned a result sea-mile cannot use, such as a missing length or geometry. |
| `implausible_route` | The route failed the physical plausibility check. |

A missing routing extra is not a `routing_error`. A route call without the extra raises
`ImportError`, which the CLI prints to `stderr` with exit code 2.

## Command data shapes

| Command | `data` shape |
| --- | --- |
| `info` | object with `registry_records`, `providers`, and `data_directory` |
| `search` | array of grouped ports, or source records with `--all-sources` |
| `show` | one port record object |
| `near` | array of grouped ports by distance, or source records with `--all-sources` |
| `route` | object with the route summary, both distances, and a quality flag |
| `matrix` | object with `ports` and `distances_nmi` |
| `match` | array of one decision per input row, each with `rules_applied` and `candidates` |
| `data download` | the download manifest object |
| `data build` | the build manifest object |
| `data prepare` | object with `download` and `build` manifests |
| `data verify` | the verification report object |
| `data lock` | the source lockfile object |

The `export` command writes CSV or GeoJSON selected by `--format`. The `tui`
command is interactive. Neither command implements `--json`.
