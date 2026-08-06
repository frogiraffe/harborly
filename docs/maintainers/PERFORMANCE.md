# Performance

`scripts/benchmark.py` builds a synthetic registry and measures build time, search operations, nearest-port queries, and distance matrix calculation.

## Reference Run (harborly 1.0.0)

Measurements refreshed on 2026-08-06:

- OS: Linux x86_64
- Python: 3.14.6
- harborly: 1.0.0
- Registry size: 40,000 synthetic records
- Spatial index: SciPy k-d tree

Run command:

```bash
uv run python scripts/benchmark.py 40000 --matrix-size 250
```

| Measurement | Result |
| --- | ---: |
| Registry build | 384.9 ms |
| Exact search | 12.638 ms/op |
| Prefix search | 14.236 ms/op |
| Fuzzy search | 36.382 ms/op |
| Grouped search | 13.608 ms/op |
| Nearest | 0.764 ms/op |
| Nearest with country filter | 0.879 ms/op |
| 250-port dense matrix (31,125 routes) | 0.227 s |
| Process peak memory | 338.2 MB |

## Matching Performance

`benchmarks/matching_performance` profiles `PortRegistry.match_names` for bulk CSV matching.

Run command:

```bash
uv run python -m benchmarks.matching_performance --rows 300 --profile-rows 200 --out benchmark-results
```

Measurements on 2026-08-06:

- Python: 3.14.6
- Registry: bundled data (20,070 rows)

| Bucket | Cold median | Cold p90 | Cold throughput | Warm throughput |
| --- | ---: | ---: | ---: | ---: |
| exact_only | 9.34 ms | 9.94 ms | 106.1 rows/s | 241,135.3 rows/s |
| fuzzy_typo | 13.01 ms | 18.00 ms | 74.0 rows/s | 169,008.1 rows/s |
| country_less | 9.19 ms | 10.08 ms | 108.4 rows/s | 246,185.0 rows/s |
| mixed | 9.69 ms | 16.58 ms | 90.9 rows/s | 205,586.9 rows/s |

## Notes

- SciPy k-d tree accelerates unfiltered nearest-port queries.
- `matrix --edge-csv` streams edges without high peak memory.
- Benchmark numbers are reference values, not hard performance guarantees.
