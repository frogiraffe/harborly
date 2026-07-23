# Migration guide

How to move to 1.0 from an earlier version. Each change below warns or is documented
before it becomes an error.

## JSON output is a versioned envelope

Since 0.3, every `--json` response is an envelope, not a bare array or object:

```json
{ "schema_version": "1", "command": "search", "data": [], "warnings": [] }
```

Read `schema_version` first, then the `data` field. A recoverable error carries an
`error` object instead of `data` and exits 2. Anything that parsed the previous bare JSON
must read `data` now. See [Output schemas](OUTPUT_SCHEMAS.md).

## The top-level namespace is smaller

Since 0.7, `sea_mile.__all__` lists the core types only. The lower-level helpers below
still import from the top level for one release, with a `DeprecationWarning`, and then
that top-level access is removed. Import each from the module named here.

| Name | Import from |
| --- | --- |
| `validate_coordinate`, `CoordinateCheck`, `great_circle_nmi` | `sea_mile.geo` |
| `canonical_key`, `normalize_display_text` | `sea_mile.text` |
| `parse_wpi_dms`, `parse_unlocode_coordinates` | `sea_mile.sources` |
| `decide_exact_match`, `ExactMatchDecision`, `MatchCandidate` | `sea_mile.matching` |
| `PortSearchResult`, `NearbyPortResult`, `NearbyPortGroup` | `sea_mile.ports` |
| `assign_canonical_ids` | `sea_mile.canonical` |
| `build_reference_registry`, `download_reference_data` | `sea_mile.build` |

## Some modules moved

Also since 0.7, several lower-level modules were renamed or grouped. The old module paths
keep working for one release and warn on import. Update to the new path.

| Old module | New module |
| --- | --- |
| `sea_mile.normalization` | `sea_mile.text` |
| `sea_mile.quality` | `sea_mile.geo` |
| `sea_mile.reference` | `sea_mile.sources` |
| `sea_mile.geonames` | `sea_mile.sources` |
| `sea_mile.osm` | `sea_mile.sources` |
| `sea_mile.registry_build` | `sea_mile.build` |
| `sea_mile.source_data` | `sea_mile.build` |

For example:

```python
# before
from sea_mile.registry_build import build_reference_registry
from sea_mile.source_data import download_reference_data

# after
from sea_mile.build import build_reference_registry, download_reference_data
```

## Timeline

A deprecated name or path warns for one minor release and is removed no earlier than the
next minor release. To find every use in your code, run Python with warnings visible:

```bash
python -W error::DeprecationWarning -c "import your_module"
```
