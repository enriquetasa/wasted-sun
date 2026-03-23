# Wasted Sun

Flask dashboard for **peninsula** “unused solar” metrics: **quarter-hourly** `qh_*_mwh` columns per `date_day` in **PostgreSQL** (i3dia-style wide rows, or **mock** data locally), rolled up to **24 hourly** chart bars. **Spanish by default** with an **English** language toggle, aimed at **DigitalOcean App Platform**.

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

Open `/` (redirects to today) or `/2024-06-15/`.

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

## Docker / App Platform

Build and run:

```bash
docker build -t wasted-sun .
docker run --rm -p 8080:8080 -e SECRET_KEY=dev -e BASE_URL=http://localhost:8080 wasted-sun
```

On [DigitalOcean App Platform](https://www.digitalocean.com/products/app-platform), connect the repo or container, set **HTTP port** `8080`, and configure environment variables (`SECRET_KEY`, `BASE_URL`, `DATABASE_URL`, etc.). Use a **trusted source** or **VPC** connection to Postgres when possible.

See [DATA_CONTRACT.md](DATA_CONTRACT.md) for the expected SQL schema and [`.env.example`](.env.example) for all options.
