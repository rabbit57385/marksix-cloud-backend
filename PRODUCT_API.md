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

`GET /api/v1/marksix/overview` has no configurable parameters. It always uses
six main numbers (`include_special=false`) and returns:

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
  include_special is false, theoretical_probability is 6/49, window is null,
  actual_draw_count and available_draw_count describe all available analysis
  records. first_available_date, latest_draw, cutoff_draw and cutoff_date
  identify the data used.

One connection and one SELECT produce one immutable snapshot. Every component
uses it; computation makes no additional DB calls. A subsequent request reads
fresh data. No HTTP cutoff control is added; the existing repository's cutoff
mechanism remains available internally. There is no cache or HKJC call on GET.

The SQL explicitly filters draw_date >= 2020-01-01, and snapshot construction
also excludes earlier records. Overview latest/recent therefore refer to the
analysis scope. Existing raw latest/recent endpoints remain unfiltered archives.
1993 records are retained in PostgreSQL and cannot supply overview warm-up.

All four windows must be complete. Ratio = count / (window * 6/49).
Ratio 1 is the theoretical average, not a prediction or winning probability.
Special number is returned separately and never contributes to primary counts.
Missing counts observed draws backwards from the same cutoff: latest presence
is zero. Never-seen numbers have missing_periods equal to available history,
is_lower_bound=true and null last_draw/last_date. No archive completeness claim.

Overview errors: 404 for no analysis draws; 409 with required_draw_count=100
and actual_draw_count for insufficient history; 503 for missing DB configuration,
driver failure or invalid stored draws. No fallback data or partial overview.

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
