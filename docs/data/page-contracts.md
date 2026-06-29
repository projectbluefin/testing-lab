# Page-oriented dashboard data contracts

These contracts split the factory dashboard into page-owned JSON files so each deep page can load only the data it needs.

## Shared rules

All files follow the same starter pattern:

- `schema_version`: contract version for the file.
- `_meta`: artifact-level metadata (`page`, `description`, `generated_at`, `starter_artifact`, `status`).
- `summary_metrics[]`: page headline metrics. Every metric row must include `source_url`, `collected_at`, and `derivation`.
- `rows[]`: the primary page records. Every row must include:
  - `source_url`: canonical evidence link for the row.
  - `collected_at`: when this JSON row was assembled.
  - `derivation`: how the row was computed from source inputs.
  - `state`: `available` or `unavailable`.
  - `state_reason`: explicit reason when the row cannot support runtime claims yet.
- Placeholder values use `null` plus `state: "unavailable"`; collectors must never invent values.

## `docs/data/upstream-status.json`

Purpose: one row per tracked upstream stream for both `/upstream` (non-Bluefin families) and `/bluefin` (Bluefin, Bluefin-LTS, Dakota) pages.

### Top-level shape

- `_meta`
- `summary_metrics[]`
- `groups[]`: logical families shown in the page nav/filtering.
- `rows[]`: concrete upstream streams.

### Row shape

| Field | Meaning |
| --- | --- |
| `id` | Stable stream id (`bluefin-testing`, `fedora-bootc-stable`) |
| `group` | `gnome-os`, `fedora-bootc`, `projectbluefin`, `ublue` |
| `variant` | Product/stream name |
| `display_name` | Human label for the page |
| `publisher_repo` | Source repo when known |
| `org` | Owning org when known |
| `branch` | Stream/tag tracked by the collector |
| `published_at` | Upstream release publish time |
| `freshness_age_days` | Days since `published_at` |
| `open_prs` | Optional repo pressure signal |
| `state` / `state_reason` | Explicit availability contract |
| `source_url` / `collected_at` / `derivation` | Provenance for the row |

## `docs/data/tests-matrix.json`

Purpose: one row per `(variant, branch, suite)` result for the `/tests` page.

### Top-level shape

- `_meta`
- `summary_metrics[]`
- `dimensions`: distinct variants/branches/suites for filters.
- `rows[]`: concrete matrix cells.

### Row shape

| Field | Meaning |
| --- | --- |
| `id` | Stable matrix key (`bluefin-testing-smoke`) |
| `variant` / `branch` / `suite` | Page filter dimensions |
| `result_status` | Published status from `docs/results/*.json` |
| `last_run` | Workflow completion time for the current cell |
| `workflow_name` | Workflow evidence for drill-down |
| `scenarios_total` / `scenarios_failed` | Current scenario counts |
| `pass_rate` | Derived percentage or `null` when unavailable |
| `history_points` | Count of historical entries already published |
| `results_path` / `screenshot_path` / `screenshot_url` | Artifact links |
| `state` / `state_reason` | Explicit availability contract |
| `source_url` / `collected_at` / `derivation` | Provenance for the row |

## `docs/data/applications-matrix.json`

Purpose: app-first rows for the `/applications` page. V1 currently tracks Bazaar and Firefox.

### Top-level shape

- `_meta`
- `summary_metrics[]`
- `applications[]`: app catalog entries.
- `rows[]`: one row per `(app_id, variant, branch)`.

### Application catalog shape

| Field | Meaning |
| --- | --- |
| `id` | Stable app id (`bazaar`, `firefox`) |
| `display_name` | Page label |
| `scope` | Current rollout scope (`v1`) |
| `primary_suite` | Preferred evidence source |
| `fallback_suites` | Coarser stop-gap evidence sources |
| `source_url` / `collected_at` / `derivation` | Provenance for the catalog entry |

### Row shape

| Field | Meaning |
| --- | --- |
| `id` | Stable key (`bazaar-bluefin-testing`, `firefox-bluefin-testing`) |
| `app_id` | Foreign key into `applications[]` |
| `variant` / `branch` | Page filter dimensions |
| `primary_suite` | Intended app evidence lane |
| `primary_result_status` | Published status for the primary suite |
| `primary_last_run` | Latest run for the primary suite |
| `scenario_total` / `scenario_failed` | App result totals when available |
| `fallback_signal_count` | Number of coarse fallback signals attached |
| `fallback_signals[]` | Optional coarse evidence rows (same provenance rules) |
| `state` / `state_reason` | Explicit availability contract |
| `source_url` / `collected_at` / `derivation` | Provenance for the row |

## Starter-artifact intent

These files are implementation-ready contracts plus honest seed data. Later collector work should replace starter `unavailable` rows with live evidence, not redesign the shape.
