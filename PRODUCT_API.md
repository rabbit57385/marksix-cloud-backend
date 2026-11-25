# MarkSix product API — Phase 5A

Existing endpoints remain unchanged:

| GET path | Behavior |
| --- | --- |
| `/health` | Process liveness only; does not check DB or HKJC |
| `/api/v1/marksix/latest` | Latest raw draw; 404 if empty |
| `/api/v1/marksix/recent-draws` | Raw draws newest first; limit defaults to 20, range 1..200 |
| `/api/v1/marksix/draw-counts` | Window 10/30/50/100 (default 30), include_special defaults false |
| `/api/v1/marksix/missing-numbers` | Available analysis history, include_special defaults false |

## Homepage overview

`GET /api/v1/marksix/overview` accepts `include_special` (default false). The default uses six main
numbers and true includes the actual special ball. Both modes return:

- `latest`: existing Draw contract: draw, date, numbers[6], special_number.
- `recent_draws`: latest 20 analysis draws, newest first, same Draw contract.
- `momentum`: keys `10`, `30`, `50`, `100`, each the complete existing
  DrawCountsResponse. Each includes window, actual_draw_count,
  theoretical_probability, include_special, cutoff_draw/date and 49 numbers.
  Number fields: number, count, theoretical_count, difference_from_average,
  momentum_ratio.
- `missing`: existing MissingNumbersResponse, including 49 entries with number,
  missing_periods, is_lower_bound, last_draw and last_date.
- `analysis`: existing SnapshotMetadata. analysis_start_date is `2020-01-01`,
  include_special matches the request, theoretical_probability is 6/49 or 7/49, window is null,
  actual_draw_count and available_draw_count describe all available analysis
  records. first_available_date, latest_draw, cutoff_draw and cutoff_date
  identify the data used.

`GET /api/v1/marksix/analysis` accepts the same mode, defaults to false,
and returns the same V7 fields for all 49 numbers, using at least 101 draws.
`GET /api/v1/marksix/count-missing-cross` accepts `include_special` and
`window` (10/30/50/100, default 30). It applies the existing A7 v1.1 cross
formula and A2/A3/A4 candidate thresholds to the MarkSix mode-specific current
and previous snapshots. Both endpoints expose the source revision header.

One connection and one SELECT produce one immutable snapshot. Every component
uses it; computation makes no additional DB calls. A subsequent request reads
fresh data. No HTTP cutoff control is added; the existing repository's cutoff
mechanism remains available internally. There is no cache or HKJC call on GET.

The SQL explicitly filters draw_date >= 2020-01-01, and snapshot construction
also excludes earlier records. Overview latest/recent therefore refer to the
analysis scope. Existing raw latest/recent endpoints remain unfiltered archives.
1993 records are retained in PostgreSQL and cannot supply overview warm-up.

All four windows must be complete. Ratio = count / (window * theoretical_probability).
Ratio 1 is the theoretical average, not a prediction or winning probability.
Special number is returned separately and contributes to counts only in seven-ball mode.
Missing counts observed draws backwards from the same cutoff: latest presence
is zero. Never-seen numbers have missing_periods equal to available history,
is_lower_bound=true and null last_draw/last_date. No archive completeness claim.

Overview errors: 404 for no analysis draws; 409 with required_draw_count=100
and actual_draw_count for insufficient history; 503 for missing DB configuration,
driver failure or invalid stored draws. No fallback data or partial overview.

## Historical grades (P1-03)

GET /api/v1/marksix/grade-history accepts window 10/30/50/100 (default 30)
and include_special (default false). It returns the existing history envelope
with status, source_revision and data, using the MarkSix formula identifier
marksix_v7_grade_history_v1. The snapshot ID is the hash part of the source
revision, shared by all windows and both modes for the same stored history.
Each result uses the latest 100 draws strictly preceding its target. The
target's main and special balls are used only to count actual hits, after
grades have been determined. The special ball remains separate in both modes.
Expected hits use candidate count times 6/49 or 7/49.

The returned count is limited to targets with at least 100 preceding draws.
With insufficient history, complete_window is false and incomplete_reason is
insufficient_pre_draw_history. An empty result has no fabricated grades.
The endpoint reads one immutable MarkSix snapshot and returns its revision
in X-MarkSix-Source-Revision, with no database writes or official API calls.

## Existing updater (inventory; not executed in Phase 5A)

From repository root:

```console
python -m marksix_cloud_backend.update_marksix --last-n 20
```

Default is 20, accepted range 1..200. Official HKJC query/headers/normalization
remain unchanged. Identical existing draws count as existing; differences count
as conflict with field-level diagnostics and no overwrite. Each draw has its
own transaction. DB failures roll back that draw and increment failed; earlier
commits persist. HKJC failure returns batch_error and exit code 1 before writes.
Missing DATABASE_URL or connection failure returns a sanitized batch_error and
exit code 1. Any conflict/failed count also produces exit code 1. No scheduler.
Backfill tooling is not included in this deployment copy.

## Future Render configuration (not deployed)

Use repository root as the working directory (leave Root Directory empty):

```text
Build Command: pip install -r requirements.txt
Start Command: uvicorn marksix_cloud_backend.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Required application environment: DATABASE_URL pointing to the existing shared
app539 database with its initialized marksix schema. All production SQL uses
qualified marksix.draws. No DB creation or migration runs on startup.
PORT is supplied by Render. Keep credentials in service environment settings.
Use an explicit tested Python runtime for reproducibility (local checks use
Python 3.13). No HKJC cookie/token, Firebase or AdMob configuration is needed.
requirements.txt contains FastAPI, Pydantic, requests, psycopg[binary], uvicorn;
no research dependencies were added.

Commands follow https://render.com/docs/deploy-fastapi with this repository's
package path. The package is included in this standalone deployment copy.
A clean Render/Linux dependency install and live DB smoke test remain necessary
before deployment; local offline tests do not establish remote connectivity,
DB freshness or load capacity. The current design reads all post-2020 history
once per overview, without pooling or caching.

## Offline validation

This copy includes selected production/API/updater tests only. The original
workspace probe comparison explicitly skips when that external probe is absent.
Overview tests cover one-query access, shared snapshot/cutoff, contracts/formulas,
excluded 1993 records, missing bounds, empty/insufficient history, DB errors and
independent-request refresh. Run the selected suite using the clean virtual
environment as documented in README.md.

## Draw synchronization (P1-01 local candidate)

The API process does not start a scheduler or run a migration. Apply
`draw_sync_migration.sql` explicitly after database approval, then configure
`MARKSIX_CATCH_UP_TOKEN` on the server and in the scheduler secret store.
Inspect the hosting dashboard for an existing MarkSix schedule and select one
owner before enabling the repository workflow. Both scheduled and manually
triggered jobs are skipped unless the repository Actions variable
MARKSIX_DRAW_SYNC_ENABLED is explicitly set to true. Leave it unset or false
until production approval and a successful manual catch-up. Do not configure
the scheduler secret before that approval. The workflow sends one request
per run. A later schedule retries a transient failure without replaying an
uncertain POST. The CLI equivalent is
`python -m marksix_cloud_backend.draw_sync`.

`GET /api/v1/marksix/freshness` reports the rolling official window, latest
draw, and revision. `POST /api/v1/marksix/admin/catch-up` is server-side only,
requires Bearer authentication, and uses a PostgreSQL lock and cooldown shared
with the CLI. A batch succeeds atomically or rolls back on conflict. A conflict
requires investigation, and existing draw records are preserved.

The freshness revision hashes normalized draws since 2020. Analysis, overview,
counts and missing responses expose it in `X-MarkSix-Source-Revision`. Latest
and recent draws expose the same header on `consistent=true`, using that same
analysis scope. The default raw endpoints keep their archive semantics.
Enable the V3 `MARKSIX_DRAW_SYNC` build flag only after confirming the deployed
read contract. V3 checks freshness and never holds the operator token.
