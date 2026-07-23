# Performance

These are planning numbers, not guarantees. They come from `scripts/benchmark.py`,
which builds a synthetic registry with a fixed seed and times the hot paths. Real
timings depend on your hardware, your Python build, and the shape of your data, so
treat every figure here as a rough budget and re-run the script on the machine you
care about.

## Reference machine

Every number below was measured on one laptop. Swap this block and the tables when
you re-run on different hardware.

- CPU: AMD Ryzen 7 5800H, 8 cores, 16 threads
- Memory: 13.5 GiB
- OS: Linux, kernel 7.1.3 (CachyOS)
- Python: 3.14.6
- sea-mile: the 0.6 performance branch
- pandas 3.0.3, rapidfuzz 3.14.5, scipy 1.18.0

The laptop runs on battery-aware frequency scaling, so a desktop with a fixed clock
will usually post faster and steadier numbers.

## How to reproduce

```bash
python scripts/benchmark.py 40000
python scripts/benchmark.py 40000 --no-kdtree
```

The first run uses the scipy k-d tree from the `fast` extra. The second sets it aside
and measures `nearest` on the plain scan path. Pass any record count as the first
argument. Run-to-run variance is around ten to twenty percent, so read the numbers as
ranges, not exact values.

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
times faster for an open `nearest` query. Install the `fast` extra when you run
coordinate lookups over a large registry.

A country filter closes most of the gap on its own. It narrows the candidates before
the distance work, so `nearest` with a `country_code` reads about the same with or
without the k-d tree. The k-d tree earns its place mainly on wide, unfiltered lookups.

## What these numbers are not

- Not a service-level guarantee. They describe one machine on one day.
- Not from real port data. The registry is synthetic and collision-heavy, which is
  hard on search and easy on memory.
- Not a registry object size. Peak memory is the whole process, so subtract the
  roughly 150 MB interpreter and pandas baseline to reason about the registry alone.
- Not stable to the millisecond. Expect ten to twenty percent drift between runs.

To get numbers that match your own deployment, run `scripts/benchmark.py` on that
hardware with a record count close to your registry size.
