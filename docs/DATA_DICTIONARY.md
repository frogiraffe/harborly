# Data dictionary

Every field a public model serializes through `to_dict`, with its type, whether it
can be null, its unit, and its meaning. These names are part of the versioned JSON
envelope (`schema_version` 1). They do not change without a schema version bump. For
the enum value lists (status, confidence tier, reason code, quality flag) and the
envelope shape, see [Output schemas](OUTPUT_SCHEMAS.md).

Coordinates are WGS84 decimal degrees. Distances are nautical miles. A null latitude
or longitude means the source gave no conflict-free coordinate, never zero.

## Port

One provider record. It is not a cross-source consensus record.

| Field | Type | Null | Meaning |
| --- | --- | --- | --- |
| `registry_id` | string | no | Stable record id, `PROVIDER:provider_id` (for example `WPI:44860`). |
| `provider` | string | no | Source provider, one of `NGA_WPI`, `UN_LOCODE`, `GEONAMES`, `OSM`. |
| `provider_id` | string | no | The record id within its provider. |
| `country_code` | string | no | ISO 3166-1 alpha-2, uppercase, empty when the source gave none. |
| `name` | string | no | Display name, Unicode-normalized with accents preserved. |
| `latitude` | number | yes | Degrees north, in `-90..90`. |
| `longitude` | number | yes | Degrees east, in `-180..180`. |
| `unlocode` | string | yes | UN/LOCODE for the record when known. |
| `function_code` | string | yes | Provider function marker (a WPI port, a UN/LOCODE function string). |
| `source_version` | string | no | The source snapshot the record was built from. |
| `coordinate_resolution` | string | yes | `arc_second`, `arc_minute`, or null, the precision of the coordinate. |
| `variant_count` | integer | no | How many raw variants of this record collapsed into one. |
| `coordinate_conflict` | boolean | no | True when variants of this record disagreed on location. |
| `canonical_id` | string | no | The physical-port identity this record belongs to, empty until grouped. |

## PortSearchResult

A `search` hit. It carries the flat `Port` fields above plus the three below, so a
search row is a `Port` with its match provenance.

| Field | Type | Null | Meaning |
| --- | --- | --- | --- |
| `matched_alias` | string | no | The alias string that matched the query. |
| `match_method` | string | no | How it matched, one of `exact`, `prefix`, `fuzzy`, `unlocode`. |
| `name_score` | number | no | Similarity of the query to the matched alias, 0 to 100. |

## PortGroup

One physical port, built by grouping records across providers. A `search --grouped`
or `near --grouped` row.

| Field | Type | Null | Meaning |
| --- | --- | --- | --- |
| `name` | string | no | Display name of the representative record. |
| `country_code` | string | no | Country of the representative record. |
| `canonical_id` | string | no | Identity shared by every member. |
| `unlocode` | string | yes | UN/LOCODE of the group when a member has one. |
| `sources` | array of string | no | The providers that describe this port. |
| `latitude` | number | yes | Representative latitude. |
| `longitude` | number | yes | Representative longitude. |
| `coordinate_conflict` | boolean | no | True when independent members disagree on location. |
| `best_score` | number | no | Name score of the representative member against the query. |
| `match_method` | string | no | Match method of the representative member. |
| `best_id` | string | no | `registry_id` of the representative member. |
| `members` | array of Port | no | Every record grouped into this port. |

## BatchMatchResult

One decision from `match`. The `sea_mile_*` columns that `match --output` appends are
derived from these fields.

| Field | Type | Null | Meaning |
| --- | --- | --- | --- |
| `query` | string | no | The input name that was matched. |
| `country_code` | string | yes | The country hint used, when a country column was given. |
| `status` | string | no | `auto_resolved`, `review_required`, `unresolved`, or `manually_resolved`. |
| `confidence_tier` | string | no | `A` to `D`, higher letters are weaker evidence. |
| `selected_registry_id` | string | yes | The chosen `registry_id`, null when unresolved. |
| `reason_code` | string | no | Stable machine reason for the decision, the `MatchReason` enum. |
| `reason` | string | no | Human-readable reason. Free text, not for automation. |
| `rules_applied` | array of string | no | The ordered decision-rule tokens that produced the outcome. |
| `candidates` | array of MatchCandidate | no | The records that informed the decision. |

## MatchCandidate

A record that informed a match decision.

| Field | Type | Null | Meaning |
| --- | --- | --- | --- |
| `registry_id` | string | no | The candidate record id. |
| `provider` | string | no | The candidate provider. |
| `name` | string | no | The candidate display name. |
| `country_code` | string | no | The candidate country. |
| `latitude` | number | yes | The candidate latitude. |
| `longitude` | number | yes | The candidate longitude. |
| `unlocode` | string | yes | The candidate UN/LOCODE. |

## SeaRoute

One `route` result. `origin` and `destination` are `Port` objects.

| Field | Type | Null | Meaning |
| --- | --- | --- | --- |
| `origin` | Port | no | The origin port record. |
| `destination` | Port | no | The destination port record. |
| `distance_nmi` | number | no | Sea distance along the graph route. |
| `great_circle_nmi` | number | no | Great-circle lower bound between the endpoints. |
| `detour_ratio` | number | yes | `distance_nmi` over `great_circle_nmi`, null when the bound is zero. |
| `quality_flag` | string | no | Route quality, the `RouteQualityFlag` enum. |
| `engine` | string | no | The routing package that produced the route, for example `searoute`. |
| `engine_version` | string | no | The installed version of that package. |
| `algorithm` | string | no | The path algorithm the engine used, for example `astar`. |
| `backend` | string | no | The graph backend the engine used, for example `networkx`. |
| `restrictions` | array of string | no | The passage restrictions applied, for example `northwest`. |

`engine`, `algorithm`, and `backend` are three different things. `engine` is the
package name, `algorithm` is the search method it ran, and `backend` is the graph
library it ran on. All three are recorded so a route is reproducible.

## Match output columns

`sea-mile match --output` appends these columns to your input rows. Each maps to a
`BatchMatchResult` field, so downstream joins keep the original columns.

| Column | Source field |
| --- | --- |
| `sea_mile_status` | `status` |
| `sea_mile_reason_code` | `reason_code` |
| `sea_mile_registry_id` | `selected_registry_id`, empty when unresolved |
| `sea_mile_name` | representative record name |
| `sea_mile_country_code` | representative record country |
| `sea_mile_latitude` | representative record latitude |
| `sea_mile_longitude` | representative record longitude |
| `sea_mile_unlocode` | representative record UN/LOCODE |
