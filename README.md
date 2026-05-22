# Wasted Sun

Flask dashboard for **peninsula** “unused solar” metrics: **PostgreSQL** (i3dia-style wide `qh_*_mwh` rows), **Cube.js** (`WastedEnergy` long format), or **mock** data locally — all rolled up to **24 hourly** chart bars. **Spanish by default** with an **English** language toggle, aimed at **DigitalOcean App Platform**.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
cp .env.example .env
pybabel compile -d translations   # if you edit .po files
flask --app wasted_sun.app:create_app --debug run
```

Open `/` (redirects to the latest date in the data) or `/2024-06-15/`.

## Tests

```bash
pip install -r requirements-dev.txt && pip install -e .
pytest
```

## Translations

- Source strings in templates/Python are **English** msgids.
- **Spanish** lives in `translations/es/LC_MESSAGES/messages.po`.
- **English** catalog is empty msgstr (falls back to msgid).

After editing strings:

```bash
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d translations
# edit translations/es/LC_MESSAGES/messages.po
pybabel compile -d translations
```

## Install note

Runtime dependencies are listed in **`requirements.txt`** and duplicated in **`pyproject.toml`** so `pip install .` / Docker installs a working app. For development, use **`pip install -r requirements-dev.txt`** (or `pip install -e ".[dev]"`).

## Docker / App Platform

Build and run:

```bash
docker build -t wasted-sun .
docker run --rm -p 8080:8080 \
  -e SECRET_KEY=dev \
  -e BASE_URL=http://localhost:8080 \
  -e SESSION_COOKIE_SECURE=false \
  wasted-sun
```

Use **`SESSION_COOKIE_SECURE=false`** when testing over **plain HTTP** (e.g. local Docker); otherwise the **locale cookie** for EN/ES may not stick. Use the default **`true`** behind HTTPS in production.

`docker run` without **`DATABASE_URL`** or **`CUBE_API_URL`** uses **mock data** (with a default illustrative €/MWh unless you set **`WASTED_SUN_EUR_PER_MWH=0`**).

On [DigitalOcean App Platform](https://www.digitalocean.com/products/app-platform), connect the repo or container, set **HTTP port** `8080`, add a **`/health`** HTTP health check if the platform supports it, and configure environment variables (`SECRET_KEY`, `BASE_URL`, `DATABASE_URL`, etc.). Use a **trusted source** or **VPC** connection to Postgres when possible.

See [DATA_CONTRACT.md](DATA_CONTRACT.md) for the expected SQL schema and [`.env.example`](.env.example) for all options.

## Production data flow (Cube → Postgres)

The site serves pages from **Postgres** only. A daily **Job** pulls from Cube and upserts the wide mart.

1. Apply [`migrations/001_wasted_sun_qh_daily.sql`](migrations/001_wasted_sun_qh_daily.sql) and [`migrations/002_wasted_sun_qh_eur.sql`](migrations/002_wasted_sun_qh_eur.sql) on your database.
2. Deploy the **Job** component (see [`.do/app.yaml`](.do/app.yaml)): run `wasted-sun-sync --full` once for backfill, then schedule `wasted-sun-sync --days 7` daily.
3. Point the **web** service at Postgres (`WASTED_SUN_DATA_SOURCE=postgres`); omit `CUBE_API_*` from web env.

```bash
# Local / one-off sync (requires Cube + Postgres env)
wasted-sun-sync --days 7
wasted-sun-sync --full
wasted-sun-sync --from 2024-01-01 --to 2024-06-15 --dry-run
```

| Component | Reads | Writes | Cube credentials |
| --------- | ----- | ------ | ---------------- |
| Web (gunicorn) | Postgres | — | No |
| Job (`wasted-sun-sync`) | Cube | Postgres | Yes |

Optional: `WASTED_SUN_PG_AS_OF_META_TABLE=wasted_sun_sync_meta` and `WASTED_SUN_PG_AS_OF_META_COLUMN=last_success_at` on the web service for “as of” in the UI.

## Configuration safety

Postgres table/column names from the environment are validated; optional `WASTED_SUN_PG_AS_OF_QUERY` must be a single `SELECT` without semicolons or comments. Prefer **`WASTED_SUN_PG_AS_OF_META_TABLE`** + **`WASTED_SUN_PG_AS_OF_META_COLUMN`** for “as of” freshness. Plausible analytics env vars are validated at startup.
