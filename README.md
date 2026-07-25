# sea-mile

**Production-grade port identity, spatial search, and analytical sea routing.**
**Üretim kalitesinde liman kimliği, uzamsal arama ve analitik deniz rotalama.**

sea-mile is a typed Python SDK and CLI for resolving real-world port identities,
finding nearby ports, reviewing ambiguous CSV matches, and calculating
approximate sea-route distances in nautical miles. The package ships with a
source-aware registry, works offline for search, and preserves the public 1.x
API while its internals evolve.

sea-mile; gerçek liman kimliklerini çözmek, yakındaki limanları bulmak, belirsiz
CSV eşleşmelerini insan incelemesine sunmak ve yaklaşık deniz rotası mesafeleri
hesaplamak için tip güvenli bir Python SDK ve CLI'dır. Kaynak bilgili registry
paketle birlikte gelir; arama çevrimdışı çalışır ve iç mimari gelişirken 1.x
kullanıcı API'si korunur.

> Routes are analytical approximations on the `searoute` maritime graph. They
> are not suitable for navigation, voyage planning, or safety-critical use.
>
> Rotalar `searoute` deniz grafı üzerindeki analitik yaklaşımlardır; seyir,
> sefer planlama veya güvenlik-kritik kullanım için uygun değildir.

## Why this architecture? / Neden bu mimari?

### Stable API, modular core / Kararlı API, modüler çekirdek

The original 1,179-line `ports.py` monolith was decomposed behind the existing
`PortRegistry` facade into focused registry, search, and spatial components.
Mixin-style composition and lazy public exports keep `Port`, `PortRegistry`,
`SeaRouter`, CLI commands, JSON schema v1, and documented exceptions backward
compatible. Callers gain a maintainable core without a migration tax.

Başlangıçtaki 1.179 satırlık `ports.py` monoliti, mevcut `PortRegistry`
cephesinin arkasında registry, search ve spatial bileşenlerine ayrıldı.
Mixin-benzeri bileşim ve lazy public export yapısı; `Port`, `PortRegistry`,
`SeaRouter`, CLI komutları, JSON schema v1 ve belgelenmiş exception'larda geriye
dönük uyumluluğu korur. Kullanıcı migrasyon maliyeti ödemeden modern bir çekirdek
elde eder.

### Spatial correctness / Uzamsal doğruluk

Coordinate order is explicit at every boundary:

- `LatLon(latitude, longitude)` is the SDK/internal contract;
- `LonLat(longitude, latitude)` is the X/Y contract used by searoute and
  GeoJSON;
- cKDTree indexes Earth-centered Cartesian XYZ, derived from validated WGS84
  latitude and longitude.

Latitude is constrained to `[-90, 90]`, longitude to `[-180, 180]`, and route
lengths are checked against their great-circle lower bound. This prevents the
classic silent lat/lon inversion that can place a maritime route on land.

Koordinat sırası her sınırda açıktır: SDK içinde `LatLon(enlem, boylam)`,
searoute ve GeoJSON X/Y sınırında `LonLat(boylam, enlem)` kullanılır; cKDTree ise
doğrulanmış WGS84 değerlerinden üretilen Dünya-merkezli Kartezyen XYZ noktalarını
indeksler. Enlem `[-90, 90]`, boylam `[-180, 180]` aralığıyla sınırlıdır ve rota
uzunluğu büyük daire alt sınırına karşı kontrol edilir.

### Artifact bundling / Registry artifact paketleme

The raw registry pipeline can approach or exceed 1 GB when archives are
downloaded and expanded. That data is not hardcoded into Python. A scheduled
GitHub Actions workflow downloads pinned public snapshots, normalizes them,
computes a deterministic content hash, and opens a reviewable PR only when the
content changes. CI builds the compact Parquet registry into the wheel and
smoke-tests the resulting artifact.

Ham registry hattı arşivler indirilip açıldığında 1 GB seviyesine ulaşabilir
veya bunu aşabilir. Bu veri Python koduna gömülmez. Zamanlanmış GitHub Actions
akışı sabitlenmiş açık veri snapshot'larını indirir, normalize eder, deterministik
content hash üretir ve yalnızca içerik değiştiğinde incelenebilir bir PR açar.
CI, kompakt Parquet registry'yi wheel içine paketler ve oluşan artifact'i smoke
testten geçirir.

### Concurrency, caching, and backoff / Paralellik, cache ve backoff

An `n`-port distance matrix has `n(n-1)/2` route edges. `SeaRouter` distributes
those independent edges across a spawn-based `ProcessPoolExecutor`, avoiding
GIL contention and filling the symmetric matrix once. Use `max_workers=1` only
for debugging or constrained runtimes.

Each process opens its own short-lived SQLite connection. WAL mode,
`busy_timeout=30000`, a 30-second connection timeout, autocommit isolation, and
`BEGIN IMMEDIATE` writes make cache misses safe under concurrent writers.
Deterministic cache keys include coordinates, effective routing configuration,
engine, and engine version.

Transient backend failures—timeouts, transport errors, HTTP 429, and HTTP
5xx—receive bounded exponential backoff. Malformed geometry and other permanent
failures fail immediately. The default `searoute` engine is local, not a remote
HTTP service; the retry contract also protects pluggable remote backends.

`n` limanlı matris `n(n-1)/2` bağımsız rota kenarı içerir. `SeaRouter` bu
kenarları spawn tabanlı `ProcessPoolExecutor` ile process'lere dağıtır ve simetrik
matrisi tek kez doldurur. Her process kısa ömürlü kendi SQLite bağlantısını açar.
WAL, 30 saniyelik connection/busy timeout, autocommit isolation ve
`BEGIN IMMEDIATE` yazımları eşzamanlı cache miss yarışlarını güvenli kılar.
Timeout, transport, HTTP 429 ve 5xx hataları sınırlı exponential backoff alır;
kalıcı veri hataları hemen döner.

### Data contracts and quality / Veri sözleşmeleri ve kalite

Strict Pandera schemas protect human-reviewed decision CSVs, generated
`review.csv` rows, and distance-matrix edges. They reject extra columns,
duplicate or missing row IDs, invalid types, non-finite distances, and
out-of-range coordinates. The same release gate runs Ruff, mypy, pytest, wheel
builds, and multi-version CI through `uv`.

Katı Pandera şemaları insan onaylı decision CSV'lerini, üretilen `review.csv`
satırlarını ve mesafe matrisi kenarlarını korur. Fazla kolon, tekrarlı/eksik
satır ID'si, hatalı tip, sonlu olmayan mesafe ve sınır dışı koordinatlar reddedilir.
Aynı release kapısı `uv` üzerinden Ruff, mypy, pytest, wheel build ve çoklu Python
sürümü CI kontrollerini çalıştırır.

## Installation / Kurulum

Install the complete CLI with routing:

```bash
uv tool install 'sea-mile[routing]'
```

For a source checkout:

```bash
uv sync --dev --extra analysis --extra fast --extra routing --extra tui
uv run sea-mile info
```

The wheel contains the compact bundled registry. Search, resolution, and nearest
queries need no download; routing requires the `routing` extra.

Wheel kompakt registry artifact'ini içerir. Arama, çözümleme ve nearest sorguları
indirme gerektirmez; rota hesaplama için `routing` extra'sı gerekir.

## Python SDK

```python
from sea_mile import PortRegistry, SeaRouter

registry = PortRegistry.bundled()
origin = registry.resolve("TRMER")
destination = registry.resolve("GRPIR")

router = SeaRouter(cache_path=".cache/sea-mile/routes.sqlite3")
route = router.route(origin, destination)
matrix = router.distance_matrix(
    [origin, destination, registry.resolve("TRIST")],
    max_workers=4,
)

print(route.distance_nmi, route.quality_flag)
```

`PortRegistry.from_directory(path)` loads a local build. `resolve` accepts exact
registry IDs, canonical IDs, UN/LOCODEs, and exact aliases; it never silently
selects a fuzzy match. Ambiguity raises `AmbiguousPortError`.

`PortRegistry.from_directory(path)` yerel build yükler. `resolve`; tam registry
ID, canonical ID, UN/LOCODE ve tam alias kabul eder, fuzzy eşleşmeyi sessizce
seçmez. Belirsizlikte `AmbiguousPortError` yükselir.

See [Library API](docs/LIBRARY_API.md), [API compatibility](docs/API_COMPATIBILITY.md),
[data dictionary](docs/DATA_DICTIONARY.md), and
[output schemas](docs/OUTPUT_SCHEMAS.md).

## CLI

| Command | English | Türkçe |
| --- | --- | --- |
| `info` | Inspect the active registry | Etkin registry'yi göster |
| `search` | Exact/prefix/fuzzy search | Tam/prefix/fuzzy arama |
| `show` | Resolve one port | Tek limanı çözümle |
| `near` | Spatial nearest-neighbour query | En yakın liman sorgusu |
| `route` | Calculate one sea route | Tek deniz rotası hesapla |
| `matrix` | Process-parallel distance matrix | Process-paralel mesafe matrisi |
| `match` | Match CSV rows and emit review data | CSV eşleştir ve review üret |
| `export` | Export CSV or GeoJSON | CSV veya GeoJSON dışa aktar |
| `tui` | Launch the interactive terminal UI | Etkileşimli terminal arayüzünü aç |
| `data download` | Download source snapshots | Kaynak snapshot'larını indir |
| `data build` | Build normalized registry | Normalize registry oluştur |
| `data prepare` | Download and build | İndir ve oluştur |
| `data lock` | Pin local source integrity | Yerel kaynak bütünlüğünü sabitle |
| `data verify` | Run provenance/integrity checks | Provenance/bütünlük kontrolü |

```bash
sea-mile search Mersin --country TR
sea-mile show TRMER
sea-mile near 39.87 26.16 --country TR --limit 5
sea-mile route TRMER GRPIR --geojson route.geojson
sea-mile matrix TRMER GRPIR TRIST --cache .cache/routes.sqlite3
sea-mile export --country TR --format geojson --output tr.geojson
sea-mile match ports.csv --country-column country
```

The registry lookup order is `--data-dir`, `SEA_MILE_DATA_DIR`, the checkout's
`data/reference/processed`, then the bundled artifact.

Registry arama sırası: `--data-dir`, `SEA_MILE_DATA_DIR`, checkout içindeki
`data/reference/processed`, ardından paketlenmiş artifact.

### Human review CSV / İnsan incelemeli CSV

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --country-column country \
  --id-column row_id \
  --output matched.csv \
  --review review.csv
```

`review.csv` contains one row per candidate for `review_required` and
`unresolved` inputs. Decisions are deliberately minimal and strict:

| Column | Contract / Sözleşme |
| --- | --- |
| `row_id` | Required, non-empty, unique / Zorunlu, boş değil, benzersiz |
| `chosen_registry_id` | Required provider-qualified ID / Zorunlu provider-qualified ID |

```bash
sea-mile match ports.csv \
  --name-column port_name \
  --id-column row_id \
  --decisions decisions.csv \
  --output matched.csv
```

Unknown registry IDs, extra columns, duplicate IDs, or empty values stop the
operation before output is accepted. Applied decisions receive
`manually_resolved`.

Bilinmeyen registry ID, fazla kolon, tekrarlı ID veya boş değerler çıktı kabul
edilmeden işlemi durdurur. Uygulanan kararlar `manually_resolved` durumunu alır.

### JSON and exit codes / JSON ve çıkış kodları

Commands that support `--json` emit one schema-versioned document:

```json
{
  "schema_version": "1",
  "command": "search",
  "data": [],
  "warnings": []
}
```

Use `schema_version` and structured `error.code` in automation; human-readable
messages may evolve. Otomasyonda `schema_version` ve yapısal `error.code`
kullanın; kullanıcı mesajları değişebilir.

| Exit code | Meaning / Anlam |
| --- | --- |
| `0` | Success, including empty results / Başarılı, boş sonuç dahil |
| `1` | `data verify` found failed checks / `data verify` hata buldu |
| `2` | Validation, data, resolution, routing, or dependency error / Doğrulama, veri, çözümleme, rota veya bağımlılık hatası |
| `130` | Interrupted with `Ctrl-C` / `Ctrl-C` ile kesildi |

## Reproducible data builds / Tekrarlanabilir veri build'i

```bash
sea-mile data prepare
sea-mile data verify
sea-mile data lock
sea-mile data build --lock sea-mile.lock.json
```

Snapshots are bounded by timeout and retry policies. The lock records URL,
snapshot label, byte size, and SHA-256, while the normalized registry carries
provider versions and a deterministic content hash.

Snapshot indirmeleri timeout ve retry politikalarıyla sınırlıdır. Lock; URL,
snapshot etiketi, byte boyutu ve SHA-256 kaydeder; normalize registry provider
sürümlerini ve deterministik content hash'i taşır.

The bundled data derives from NGA World Port Index and GeoNames. Local builds
can add UN/LOCODE and user-supplied OpenStreetMap data. See
[sources, attribution, and limitations](docs/SOURCES_AND_LIMITATIONS.md).

## Development and release gate / Geliştirme ve release kapısı

```bash
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
uv build
```

Python 3.11–3.13 are tested on Linux; the latest supported version is also
tested on macOS and Windows. Security reports follow [SECURITY.md](SECURITY.md);
contributions follow [CONTRIBUTING.md](CONTRIBUTING.md).

Python 3.11–3.13 Linux üzerinde; desteklenen son sürüm ayrıca macOS ve Windows
üzerinde test edilir. Güvenlik bildirimleri [SECURITY.md](SECURITY.md),
katkılar [CONTRIBUTING.md](CONTRIBUTING.md) üzerinden yürütülür.
