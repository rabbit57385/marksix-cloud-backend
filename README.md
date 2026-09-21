# MarkSix backend

Independent deployment copy for the MarkSix FastAPI service. Python 3.13 is the
local validation runtime. Production modules and selected offline tests are
copied unchanged from the tested source.

## Database

PostgreSQL may share an instance and database with 539. MarkSix uses the separate
schema marksix and table marksix.draws; application SQL explicitly qualifies it.
Provide DATABASE_URL through the environment. Never commit connection strings,
passwords, tokens or real .env files.

The existing production database already has the required schema/table.
init_db.sql is schema documentation and a manual initial-setup/maintenance
artifact only. Its original dedicated-database comment is retained because the
SQL file is an unchanged copy; the deployment architecture uses a shared
database with an independent marksix schema.

**DO NOT RUN AUTOMATICALLY ON RENDER STARTUP.**
Do not rerun init_db.sql against the existing production table. Build and startup
do not create tables or run migrations.

## API

- GET /health: process liveness, no database required.
- GET /api/v1/marksix/latest
- GET /api/v1/marksix/recent-draws?limit=20
- GET /api/v1/marksix/draw-counts?window=30&include_special=false
- GET /api/v1/marksix/missing-numbers?include_special=false
- GET /api/v1/marksix/overview

See PRODUCT_API.md for contracts. Overview uses one immutable analysis snapshot,
six main numbers and 10/30/50/100 complete windows. Analysis starts at 2020-01-01;
1993 archive records remain in the database but are excluded from analysis.

## Local offline validation

From this repository root on Windows:

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements-test.txt
    .venv\Scripts\python.exe -B -m unittest discover -s marksix_cloud_backend/tests -t . -p "test_*.py" -v

Selected tests use mocks and do not need DATABASE_URL or live HKJC.
The original-probe parity test explicitly skips when the original workspace
probe is absent. This does not affect runtime imports.
The injected TestClient currently emits an httpx compatibility deprecation
notice; production endpoints do not depend on httpx.

## Explicit updater

After DATABASE_URL has been configured, this separate command fetches official
HKJC data and writes to marksix.draws:

    python -m marksix_cloud_backend.update_marksix --last-n 20

Default: 20 draws; range: 1..200. Identical existing records are retained;
conflicts report differences without overwriting. Each draw has its own
transaction. No updater or scheduler runs automatically with the API.
For offline CLI validation only:

    python -m marksix_cloud_backend.update_marksix --help

## Render configuration (not deployed)

Root Directory: leave empty (repository root).
Build Command: pip install -r requirements.txt
Start Command: uvicorn marksix_cloud_backend.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
Environment: DATABASE_URL; PORT is supplied by Render.

Use the existing 539-postgres Internal Database URL for a service in the same
account and region, pointing to the shared database containing marksix.draws.
Store it in Render environment settings only. Pin the tested Python runtime in
deployment settings. /health proves process liveness, not database readiness.
A clean Linux install and read-only live database smoke test remain deployment
checks; Windows offline validation does not establish remote connectivity.
