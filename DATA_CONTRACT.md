# Data contract (PostgreSQL)

The app expects **hourly** rows covering each **Europe/Madrid** calendar day you want to display.

## Table shape (configurable via environment)

| Concept        | Default env column | Type (recommended)      |
| -------------- | ------------------ | ----------------------- |
| Hour bucket    | `bucket_start`     | `timestamptz`           |
| Unused energy  | `mwh_unused`       | `numeric`               |
| Euro estimate  | `eur_waste`        | `numeric`               |

Table name default: `wasted_sun_hourly` (`WASTED_SUN_PG_TABLE`).

## Semantics

- **`bucket_start`**: start of the hour in local terms; stored as `timestamptz` is preferred. Rows must fall inside `[day 00:00, next day 00:00)` in **Europe/Madrid** for a complete day.
- **Day total**: `SUM(mwh_unused)` and `SUM(eur_waste)` over those rows.
- **YTD**: same sums from `January 1 00:00 Europe/Madrid` through the **end** of the selected day (exclusive upper bound = start of next day).
- **Headline “per hour”**: arithmetic **mean** of the hourly values for that calendar day (implemented in Python after fetch).
- **`as_of`**: `MAX(bucket_start)` for the table unless you set `WASTED_SUN_PG_AS_OF_QUERY` to a SQL statement returning one timestamp.

## Read-only role

Grant `SELECT` only on the table (and any meta table used for `as_of`).

## Mock mode

Without `DATABASE_URL`, or with `USE_MOCK_DATA=true`, the app uses deterministic fixtures and ignores Postgres.
