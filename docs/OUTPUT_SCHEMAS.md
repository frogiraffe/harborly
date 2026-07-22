# Output schemas

Every command that supports `--json` prints one JSON document to stdout. The document
is a versioned envelope. Automation should read `schema_version` first and then branch
on whether `data` or `error` is present.

A machine-readable JSON Schema for the envelope lives at
[`schemas/envelope-1.schema.json`](schemas/envelope-1.schema.json), and the test suite
validates the output of every `--json` command against it.

## Success envelope

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
| `schema_version` | string | Envelope version. It changes only on a breaking change. |
| `command` | string | The command that produced the document, such as `search` or `data prepare`. |
| `data` | object or array | The command result. Its shape depends on the command. |
| `warnings` | array of string | Non-fatal notes. Empty when there are none. |

## Error envelope

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
| `registry_data_error` | The local registry files are missing or invalid. |
| `source_data_error` | A public snapshot could not be downloaded or read. |
| `usage_error` | A bad argument or a missing filter, such as a one-port `matrix`. |

The `message` is human text and may change between releases. Automation should branch on
`code`, not on `message`. The `details` object is reserved for structured context and
may be empty.

## Enumerated values

Some `data` fields carry a fixed set of string values.

### `match` decisions

| Field | Values |
| --- | --- |
| `status` | `auto_resolved`, `review_required`, `unresolved` |
| `confidence_tier` | `A`, `B`, `C`, `D` |

A confidence tier is a similarity signal, not a calibrated probability.

### `route` quality flag

| Value | Meaning |
| --- | --- |
| `ok` | The route passed the basic plausibility checks. |
| `high_detour_ratio` | The route is far longer than the great-circle lower bound. |
| `coincident_endpoints` | The origin and destination are the same point. |

## Command data shapes

| Command | `data` shape |
| --- | --- |
| `info` | object with `registry_records`, `providers`, and `data_directory` |
| `search` | array of grouped ports, or source records with `--all-sources` |
| `show` | one port record object |
| `near` | array of grouped ports by distance, or source records with `--all-sources` |
| `route` | object with the route summary, both distances, and a quality flag |
| `matrix` | object with `ports` and `distances_nmi` |
| `match` | array of one decision object per input row |
| `data download` | the download manifest object |
| `data build` | the build manifest object |
| `data prepare` | object with `download` and `build` manifests |
| `data verify` | the verification report object |

The `export` command writes CSV or GeoJSON chosen with `--format`, and `tui` is
interactive, so neither uses this envelope.
