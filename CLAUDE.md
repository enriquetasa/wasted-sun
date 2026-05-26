# CLAUDE.md — Wasted Sun

## Project Overview

Wasted Sun is a Flask web dashboard that visualises solar curtailment ("wasted sun") metrics for the Spanish electricity grid. It reads energy (MWh) and cost (EUR) data from a pluggable provider, renders bilingual (ES/EN) Jinja2 pages, and exposes social-sharing routes. A companion CLI (`wasted-sun-sync`) ETL-syncs data from Cube.js into a PostgreSQL wide mart.

---

## Repository Layout

```
wasted_sun/           # Main Python package
  app.py              # create_app() factory
  views.py            # Flask Blueprint, all routes
  models.py           # DailyMetrics, HourlyPoint dataclasses
  config.py           # Config / DevelopmentConfig / ProductionConfig
  timeseries.py       # QH→hourly aggregation logic
  waste_display.py    # Signed data → positive headline magnitude
  formatting.py       # Babel locale-aware number formatters
  sql_guard.py        # SQL/URL injection hardening helpers
  exceptions.py       # ConfigurationError
  data/               # Pluggable metrics providers
    base.py           # MetricsProvider protocol + get_provider() factory
    postgres.py       # PostgresMetricsProvider
    cube.py           # CubeMetricsProvider
    cube_scope.py     # Cube dimension/measure/filter helpers
    mock.py           # MockMetricsProvider (deterministic seeded fixtures)
  sync/               # ETL: Cube → Postgres
    run.py            # wasted-sun-sync CLI entry point
    cube_loader.py    # Cube HTTP client
    materialize.py    # Cube rows → wide mart row (QH pivot)
    postgres_writer.py# Upsert + sync metadata
  static/             # style.css, kpi-animate.js
  templates/          # base.html, day.html, error.html
migrations/           # PostgreSQL schema SQL files
tests/                # Pytest test suite
translations/         # Flask-Babel i18n (es, en)
.do/app.yaml          # DigitalOcean App Platform spec
Dockerfile
wsgi.py               # Gunicorn entry point
pyproject.toml
requirements.txt
requirements-dev.txt
.env.example
DATA_CONTRACT.md      # Postgres schema & Cube semantic model spec
```

---

## Tech Stack

- **Python 3.11+**, Flask 3.x, Flask-Babel 4.x
- **Gunicorn** (production WSGI server, port 8080)
- **psycopg 3** (async-capable PostgreSQL adapter)
- **Pytest 8** (test runner)
- **Babel** (i18n extract/compile tooling)
- Frontend: Jinja2 templates, vanilla JS, Chart.js (CDN)
- Deployment: DigitalOcean App Platform

---

## Development Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
cp .env.example .env           # edit as needed
pybabel compile -d translations
flask --app wasted_sun.app:create_app --debug run
# App available at http://localhost:5000
```

The default data source is **mock** (no database required). Change `WASTED_SUN_DATA_SOURCE` in `.env` to `postgres` or `cube` for live data.

---

## Running Tests

```bash
pytest
```

Tests live in `tests/`. `conftest.py` monkeypatches the app into mock-data mode. No database or Cube server is needed. The `pyproject.toml` sets `testpaths = ["tests"]` and `pythonpath = ["."]`.

---

## Environment Variables

All app-specific vars are prefixed `WASTED_SUN_`. Key groups:

| Variable | Purpose |
|---|---|
| `WASTED_SUN_DATA_SOURCE` | `mock` / `postgres` / `cube` |
| `DATABASE_URL` | Postgres connection string |
| `WASTED_SUN_PG_TABLE` | Qualified table name (`schema.table`) |
| `WASTED_SUN_PG_COL_*` | Column name overrides |
| `WASTED_SUN_PG_QH_SLOTS` | Number of QH slots (1–200, default 100) |
| `CUBE_API_URL`, `CUBE_API_TOKEN` | Cube.js endpoint |
| `WASTED_SUN_CUBE_REDISPATCH_CODES` | Comma-separated allowlist |
| `WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES` | Comma-separated allowlist |
| `WASTED_SUN_EUR_PER_MWH` | Flat price override (else Cube field) |
| `CUBE_SKIP_YTD` | Skip slow YTD query (`true` default) |
| `PLAUSIBLE_DOMAIN`, `PLAUSIBLE_SCRIPT_URL` | Analytics (validated at startup) |
| `HOUSEHOLD_DAY_KWH` | Household analogy (default 12) |
| `APP_TIMEZONE` | Defaults to `Europe/Madrid` |

See `.env.example` for the full list and `wasted_sun/config.py` for parsing logic.

---

## Key Architectural Patterns

### Provider Protocol
`wasted_sun/data/base.py` defines a duck-typed `MetricsProvider` protocol with three methods:

```python
def earliest_date() -> date: ...
def latest_available_date() -> date: ...
def get_daily_metrics(day: date) -> DailyMetrics: ...
```

`get_provider()` selects the implementation based on `WASTED_SUN_DATA_SOURCE`. Never add ABC inheritance — keep duck typing.

### Signed vs. Headline Waste
Postgres/Cube store **signed** MWh/EUR values (curtailment is negative in some feeds). `waste_display.py` converts to **positive headline** magnitudes for the UI and YTD totals. Always use `headline_waste_mwh()` / `headline_waste_eur()` when rendering KPIs, not raw provider values.

### Quarter-Hourly (QH) to Hourly Rollup
- Data arrives in QH slots (15-min intervals), 1-indexed, up to 200 slots.
- 4 QH slots → 1 hour. Slots 97–100 overflow into hour 23 (not hour 24).
- Core logic: `timeseries.py` → `merge_qh_across_rows()`, `hourly_mwh_from_qh()`.

### SQL Injection Hardening
All Postgres identifiers (table names, column names) and the `as_of_query` SELECT are validated through `sql_guard.py` before being passed to psycopg's `sql.Identifier`. Never construct SQL strings by concatenation. `validate_as_of_select()` only allows SELECT statements.

### i18n
- Default locale: Spanish (`es`)
- English fallback: empty `msgstr` in catalog
- Locale stored in Flask `session`; overridden by `?lang=es|en` query param
- Template strings use `gettext`/`_()`. All user-visible text must have a translation entry.

---

## Translation Workflow

```bash
pybabel extract -F babel.cfg -o messages.pot .       # extract msgids
pybabel update -i messages.pot -d translations        # update .po files
# edit translations/es/LC_MESSAGES/messages.po
pybabel compile -d translations                       # compile .mo
```

The Dockerfile runs `pybabel compile` at build time — commit updated `.po` files but `.mo` files are build artifacts (`.gitignore`-safe, but currently tracked; don't remove them without checking).

---

## Database Schema

See `DATA_CONTRACT.md` for the full spec. Quick reference:

- **Wide mart table** (`wasted_sun_qh_daily` by default): one row per `(date_day, ...)`, columns `qh_1_mwh … qh_N_mwh`, `qh_1_eur … qh_N_eur`, `total_mwh`, `total_eur`, `synced_at`
- Multiple rows for the same date are merged by `merge_qh_across_rows()` (element-wise sum)
- **Sync metadata table** (`wasted_sun_sync_meta`): records success/failure timestamps per day

### Migrations
Apply in order:
```bash
psql $DATABASE_URL -f migrations/001_wasted_sun_qh_daily.sql
psql $DATABASE_URL -f migrations/002_wasted_sun_qh_eur.sql
```

---

## Sync CLI

```bash
wasted-sun-sync --days 7          # rolling 7-day window (DigitalOcean cron default)
wasted-sun-sync --full            # backfill from earliest available date
wasted-sun-sync --from 2024-01-01 --to 2024-12-31
wasted-sun-sync --days 7 --dry-run  # no writes
```

Requires `WASTED_SUN_DATA_SOURCE=postgres` and both `CUBE_*` and `DATABASE_URL` vars.

---

## Docker

```bash
docker build -t wasted-sun .
docker run --rm -p 8080:8080 \
  -e SECRET_KEY=dev \
  -e BASE_URL=http://localhost:8080 \
  -e SESSION_COOKIE_SECURE=false \
  wasted-sun
```

Production image is `python:3.12-slim-bookworm`. Port 8080 is hardcoded in the `CMD`.

---

## Routes

| Route | Description |
|---|---|
| `GET /` | Redirects to latest available date |
| `GET /<YYYY-MM-DD>/` | Day dashboard page |
| `GET /health` | Health check (200 OK) |
| `GET /set-locale/<lang>/` | Sets session locale, redirects back |

Share routes are built from the day page via query params for LinkedIn/Bluesky/X.

---

## Code Conventions

- **Type hints** throughout; Python 3.10+ union syntax (`X | None`), `from __future__ import annotations` at file top.
- **Dataclasses** for domain models (`DailyMetrics`, `HourlyPoint`); no ORM.
- **`current_app.logger`** for structured logging; include timing in ms for slow queries.
- **ISO 8601** dates everywhere (`datetime.date`, never strings in internal APIs).
- **`Europe/Madrid` timezone** for display; UTC for storage.
- **No `print()`** — use `logger`.
- **No bare `except`** — catch specific exceptions.
- Comments only where the *why* is non-obvious (workaround, invariant, domain rule). No docstrings on simple methods.

---

## Testing Conventions

- Each module in `wasted_sun/` has a corresponding `tests/test_<module>.py`.
- Use `pytest.mark.parametrize` for data-driven cases (see `test_sql_guard.py`, `test_timeseries.py`).
- Fixtures in `conftest.py`: `app` (monkeypatched Flask app, mock provider) and `client` (test client).
- Mock provider is seeded deterministically — tests can rely on specific fixture values for 2024-01-01 onwards.
- No database or external service required in tests.

---

## Deployment (DigitalOcean App Platform)

See `.do/app.yaml`. Two components:
1. **Web service** — Gunicorn, `DATABASE_URL` from managed Postgres, `WASTED_SUN_DATA_SOURCE=postgres`
2. **Scheduled job** — `wasted-sun-sync --days 7` daily at 05:00 UTC, `WASTED_SUN_DATA_SOURCE=postgres` with Cube vars

No CI/CD pipeline is configured; deploys are triggered manually via DigitalOcean platform or `doctl`.
