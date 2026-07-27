# Performance

`scripts/benchmark.py` builds a deterministic synthetic registry and measures
registry construction, search, nearest-port queries, and an optional distance
matrix. Results are reference measurements, not service-level guarantees.

## Current reference run

Measurements were refreshed on 2026-07-27 with:

- CPU: AMD Ryzen 7 5800H, 8 cores, 16 threads.
- Memory: 13.5 GiB.
- OS: Linux x86_64.
- Python: 3.14.6.
- sea-mile: 1.5.0.
- Registry size: 40,000 deterministic synthetic records.
- Spatial index: SciPy k-d tree.

Reproduce the run with:

```bash
uv run python scripts/benchmark.py 40000 --matrix-size 250
```

| Measurement | Result |
| --- | ---: |
| Registry build | 321.4 ms |
| Exact search | 12.398 ms/query |
| Prefix search | 13.602 ms/query |
| Fuzzy search | 35.923 ms/query |
| Grouped search | 13.104 ms/query |
| Nearest | 0.742 ms/query |
| Nearest with country filter | 0.855 ms/query |
| 250-port dense matrix, 31,125 routes | 0.215 s |
| Process peak memory | 254.3 MB |

Observed run-to-run latency variance is commonly 10–20%, so these values should
not be treated as thresholds.

## Matrix measurement

The benchmark matrix uses a deterministic in-process backend whose route length
is 1.1 times the great-circle distance. It runs with one worker so it measures
sea-mile's validation, scheduling, and dense-matrix allocation without mixing in
searoute graph-search variability.

The dense matrix necessarily retains `n²` floats. `SeaRouter` no longer retains
the quadratic pair list or all executor results: it generates pairs lazily and
submits fixed-size batches with bounded backpressure. Applications that do not
need a dense matrix should use `iter_distance_edges` or CLI
`matrix --edge-csv`, which streams route edges.

The matrix benchmark is opt-in. Choose a size appropriate for the machine:

```bash
uv run python scripts/benchmark.py 40000 --matrix-size 500
```

## SciPy comparison

Use `--no-kdtree` to force the vectorized scan path:

```bash
uv run python scripts/benchmark.py 40000 --no-kdtree
```

The k-d tree mainly benefits unfiltered nearest-port queries. A country filter
reduces the candidate set before distance calculation, so its benefit is
smaller for filtered queries. It does not affect name search.

## Measurement limits

- The registry is synthetic and deliberately collision-heavy.
- Matrix routing uses the deterministic benchmark backend, not searoute.
- Peak memory is the whole process, including Python, pandas, input frames,
  registry indexes, and the dense matrix.
- Results describe one machine and one run, not a service-level objective.
- Deployment sizing should be repeated on target hardware with representative
  records and routing inputs.
