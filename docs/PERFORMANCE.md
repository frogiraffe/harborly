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

## Matching performance (`match_names` bulk CSV workloads)

`benchmarks/matching_performance` profiles `PortRegistry.match_names` — the
call `match_dataframe` makes for a bulk CSV import — separately from the
`scripts/benchmark.py` numbers above, which measure `PortRegistry.search()`
directly on a synthetic registry and do not exercise `match_names` at all.

Reproduce with:

```bash
uv run python -m benchmarks.matching_performance --rows 300 --profile-rows 200 --out benchmark-results
```

Measured 2026-07-29 with:

- CPU: AMD Ryzen 5 7600, 6 cores / 12 threads.
- Python 3.14.6; pandas 3.0.3, numpy 2.5.1, rapidfuzz 3.14.5, pyarrow 25.0.0,
  pandera 0.32.1.
- Registry: bundled data, 20,070 rows, loaded in 0.115 s.
- Seed `20260729`, 300 sampled rows per bucket (900 in the shuffled `mixed`
  bucket), 200 rows profiled with `cProfile`.
- Queries: `exact_only` (clean name + correct country), `fuzzy_typo`
  (single-letter swap/drop/double + correct country), `country_less` (clean
  name, no country code), `mixed` (shuffled combination of the three).

| Bucket | Cold median | Cold p90 | Cold throughput | Warm (cache-hit) throughput |
| --- | ---: | ---: | ---: | ---: |
| exact_only | 8.96 ms | 9.69 ms | 110 rows/s | 230,153 rows/s |
| fuzzy_typo | 12.31 ms | 17.70 ms | 76 rows/s | 169,737 rows/s |
| country_less | 8.77 ms | 9.29 ms | 114 rows/s | 238,230 rows/s |
| mixed | 9.13 ms | 15.84 ms | 97 rows/s | 201,576 rows/s |

Full percentile/throughput tables, repeated-pass numbers, and the raw
`cProfile` output are in `benchmark-results/matching_performance.md` and
`.json` (not checked into version control by default; regenerate locally).

**Dominant cost, from the `cProfile` trace:** it is not fuzzy scoring.
`rapidfuzz` candidate scoring inside `AliasSearchIndex.candidates`
(`src/sea_mile/search.py:51`) accounts for well under a third of per-query
time. The dominant cost is `search_results_from_candidates`
(`src/sea_mile/_registry_search.py:59`), which calls
`candidate_aliases.merge(registry._registry, ..., validate="many_to_one")` —
**a full pandas `DataFrame.merge` against the entire 20,070-row registry on
every single query**, exact or fuzzy. In the profiled 200-row sample, that
merge (and the categorical-dtype/`MultiIndex` machinery pandas builds around
it) accounted for roughly 2.55 of 3.25 total profiled seconds — about 78% of
`match_names` time — even though a typical query only needs to enrich a
handful of candidate rows (`limit=50`, usually far fewer real hits).

This is a real, evidence-backed bottleneck, not the cold-vs-warm cache gap
(cold vs. warm differs by ~2000x because `lru_cache` skips the search path
entirely on a hit — expected and not actionable for genuinely distinct bulk
CSV rows, which rarely repeat).

**No optimization was made in this profiling pass**, per the constraint to
identify the dominant cost before changing implementation and to preserve
matching decisions and candidate ordering. The concrete, testable follow-up
this profile points to: replace the full-registry `merge` in
`search_results_from_candidates` with a lookup against `PortRegistry._by_id`
(already built as an index in `PortRegistry.__init__`, `src/sea_mile/ports.py:114`)
for just the candidate rows, instead of merging candidate aliases against the
entire registry frame. That change needs its own dedicated tests verifying
identical candidate ordering and scores before landing, so it is left as a
follow-up rather than done under this profiling task.

## Measurement limits

- The registry is synthetic and deliberately collision-heavy.
- Matrix routing uses the deterministic benchmark backend, not searoute.
- Peak memory is the whole process, including Python, pandas, input frames,
  registry indexes, and the dense matrix.
- Results describe one machine and one run, not a service-level objective.
- Deployment sizing should be repeated on target hardware with representative
  records and routing inputs.
