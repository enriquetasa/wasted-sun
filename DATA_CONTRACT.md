# Data contract (PostgreSQL)

The app expects **one or more rows per `date_day`**, each with up to **100 quarter-hourly MWh columns** (`qh_1_mwh` … `qh_100_mwh`) plus metadata. This matches wide exports such as i3dia-style daily tables. In a typical deployment those MWh values are **derived from Red Eléctrica de España (REE) data** and transformed in an **upstream pipeline** before they reach this database (mock mode uses synthetic data instead).

## Required / used columns

| Column        | Default env name   | Notes |
| ------------- | ------------------ | ----- |
| Calendar date | `date_day`         | `date` type (or timestamp castable to a day in queries). |
| Quarter-hours | `qh_1_mwh` … `qh_N_mwh` | `numeric`. Slot *i* is the *i*-th 15-minute period from **local midnight** (Europe/Madrid). `N` defaults to **100** (`WASTED_SUN_PG_QH_SLOTS`). |
| YTD helper    | `total_mwh`        | Per-row daily total; **YTD** uses `SUM(total_mwh)` over `date_day` from 1 Jan through the selected day. Should be consistent with the qh columns for that row. |

Other columns (`i3dia_id`, `redispatch`, `type`, `direction`, `concept`, `restriction_type`, …) are ignored unless you filter upstream (e.g. a **VIEW** that only exposes solar-related rows).

## Aggregation rules

1. **Same-day merge:** All rows with the same `date_day` are merged by **summing** each `qh_*_mwh` bucket independently.
2. **Day total (MWh):** Sum of all merged quarter-hour values for that day.
3. **Chart:** Quarter-hours are rolled into **24 hourly** bars: qh 1–4 → hour 0, 5–8 → hour 1, …, 93–96 → hour 23. Values in **qh_97–qh_100** (if present) are **added to hour 23** so the full day’s energy appears in the profile.
4. **Headline “per hour”:** Mean of those 24 hourly bar values (= day total MWh ÷ 24).
5. **YTD:** `SELECT COALESCE(SUM(total_mwh),0) … WHERE date_day BETWEEN Jan-1 AND selected_day`.
6. **Euros:** Not stored in this schema. Set **`WASTED_SUN_EUR_PER_MWH`** to show illustrative EUR (day, YTD, share text). Omit it (or set to **`0`**) for MWh-only. **Mock / no `DATABASE_URL`:** if the variable is **unset**, the app applies a **default demo rate** (`52` €/MWh) so local UI still shows euros; set **`WASTED_SUN_EUR_PER_MWH=0`** to force MWh-only locally.

7. **Day total vs YTD:** The **headline day total** is the **sum of merged `qh_*`**. **YTD** is **`SUM(total_mwh)`** in SQL. If those disagree in your source data, KPIs will look inconsistent—fix upstream or align columns.

## `as_of` timestamp

**Preferred (safest):** set **`WASTED_SUN_PG_AS_OF_META_TABLE`** and **`WASTED_SUN_PG_AS_OF_META_COLUMN`** to a single table and column (each a valid PostgreSQL identifier). The app runs `SELECT MAX(<column>) FROM <table>` with identifiers passed through `psycopg.sql.Identifier` — no raw SQL from env beyond those names.

**Legacy (operator-only):** **`WASTED_SUN_PG_AS_OF_QUERY`** may be a single **`SELECT …`** statement (no `;`, no SQL comments) returning one `timestamptz` / `timestamp`. It is validated with a conservative blocklist but still accepts arbitrary SQL—treat it as a **privileged, operator-only** setting and never expose it to end users or untrusted input. Prefer the meta table/column pair above whenever possible. **Do not set both** the meta pair and `WASTED_SUN_PG_AS_OF_QUERY`.

If neither is configured, the app uses **end of `MAX(date_day)`** in Europe/Madrid.

## Table and column names

`WASTED_SUN_PG_TABLE` may be **`schema.table`** or a single identifier. **`WASTED_SUN_PG_COL_*`** values must be plain identifiers (letters, digits, underscore; not reserved injection patterns). All are validated before use.

## Security note

Environment-driven SQL is limited to validated identifiers and, for `WASTED_SUN_PG_AS_OF_QUERY`, a restricted `SELECT`-only pattern. **`PLAUSIBLE_DOMAIN`** and **`PLAUSIBLE_SCRIPT_URL`** are validated at startup (hostname / `https?` script URL only).

## Table name

Set `WASTED_SUN_PG_TABLE` to your table or **VIEW** name (default in config: `wasted_sun_qh_daily`).

## Mock mode

Without `DATABASE_URL`, or with `USE_MOCK_DATA=true`, the app uses fixtures and ignores this schema.
