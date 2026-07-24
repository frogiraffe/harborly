# Performance

`scripts/benchmark.py` builds a deterministic synthetic registry and measures
registry construction, search, and nearest-port queries. Results are reference
measurements, not service-level guarantees.

## Reference machine

Measurements were collected on:

- CPU: AMD Ryzen 7 5800H, 8 cores, 16 threads
- Memory: 13.5 GiB
- OS: Linux, kernel 7.1.3 (CachyOS)
- Python: 3.14.6
- sea-mile: 1.0
- pandas 3.0.3, rapidfuzz 3.14.5, scipy 1.18.0

## How to reproduce

```bash
python scripts/benchmark.py 40000
python scripts/benchmark.py 40000 --no-kdtree
```

The first command uses the SciPy k-d tree from the `fast` extra. The second
measures the vectorized scan path. The positional argument controls record count.
Observed run-to-run variance was 10–20%.

## Build time and memory

| records | build | peak memory |
| ------- | ----- | ----------- |
| 10,000  | 220 ms  | 165 MB |
| 40,000  | 530 ms  | 210 MB |
| 100,000 | 1,160 ms | 280 MB |

Build time tracks the record count closely. Peak memory is the whole process at its
high-water mark, which covers the Python interpreter, pandas, the input frames, and
the registry itself. About 150 MB of that is the interpreter and pandas before any
registry exists, so the marginal cost per record is small at these sizes.

## Search latency

Each figure is milliseconds per query, averaged over a spread of queries.

| records | exact | prefix | fuzzy | grouped |
| ------- | ----- | ------ | ----- | ------- |
| 10,000  | 10 ms | 10 ms | 38 ms  | 10 ms |
| 40,000  | 20 ms | 22 ms | 59 ms  | 21 ms |
| 100,000 | 39 ms | 45 ms | 100 ms | 40 ms |

Fuzzy search sets the ceiling because it scores the query against every candidate
alias. The synthetic data packs many repeated names into a small set of prefixes, so
it collides far more than a real port registry. Read these as a pessimistic bound.
Real data with more distinct names tends to run faster. The k-d tree does not touch
search, so `--no-kdtree` leaves these rows unchanged.

## Nearest latency and when scipy helps

| records | k-d tree | scan only | with country filter |
| ------- | -------- | --------- | ------------------- |
| 10,000  | 1.2 ms | 2.6 ms  | 1.2 ms |
| 40,000  | 1.4 ms | 7.8 ms  | 1.5 ms |
| 100,000 | 1.7 ms | 19.8 ms | 2.3 ms |

The k-d tree lookup stays near constant as the registry grows, while the plain scan
grows in step with the record count. At 100,000 records the k-d tree is more than ten
times faster for an open `nearest` query. The `fast` extra is recommended for
large-registry coordinate workloads.

A country filter closes most of the gap on its own. It narrows the candidates before
the distance work, so `nearest` with a `country_code` reads about the same with or
without the k-d tree. The k-d tree earns its place mainly on wide, unfiltered lookups.

## Measurement limits

- Not a service-level guarantee. They describe one machine on one day.
- Not from real port data. The registry is synthetic and collision-heavy, which is
  hard on search and easy on memory.
- Not a registry object size. Peak memory is the whole process, so subtract the
  roughly 150 MB interpreter and pandas baseline to reason about the registry alone.
- Not stable to the millisecond. Expect ten to twenty percent drift between runs.

Deployment-specific measurements require running `scripts/benchmark.py` on the
target hardware with a representative record count.
