# Data contract (PostgreSQL)

The app expects **one or more rows per `date_day`**, each with up to **100 quarter-hourly MWh columns** (`qh_1_mwh` … `qh_100_mwh`) plus metadata. This matches wide exports such as i3dia-style daily tables. In a typical deployment those MWh values are **derived from Red Eléctrica de España (REE) data** and transformed in an **upstream pipeline** before they reach this database (mock mode uses synthetic data instead).

## Required / used columns

| Column        | Default env name   | Notes |
| ------------- | ------------------ | ----- |
| Calendar date | `date_day`         | `date` type (or timestamp castable to a day in queries). |
| Quarter-hours | `qh_1_mwh` … `qh_N_mwh` | `numeric`. Slot *i* is the *i*-th 15-minute period from **local midnight** (Europe/Madrid). `N` defaults to **100** (`WASTED_SUN_PG_QH_SLOTS`; range **1–200**). |
| YTD helper    | `total_mwh`        | Per-row daily **net** (algebraic sum of `qh_*`, often negative in upstream REE/Cube data). **YTD** in the app uses `SUM(ABS(total_mwh))` from 1 Jan through the selected day. Should equal the algebraic sum of qh columns for that row. |
| Quarter-hour € | `qh_1_eur` … `qh_N_eur` | Per-slot `EnergyMwh × PriceEspEurMwh` from Cube (signed net per slot). |
| Day € (net)   | `total_eur`        | Algebraic sum of `qh_*_eur`; headline uses **`ABS(total_eur)`**. |
| Sync stamp    | `synced_at`        | Set by **`wasted-sun-sync`** on each upsert (optional for reads; useful for debugging). |

Other columns (`i3dia_id`, `redispatch`, `type`, `direction`, `concept`, `restriction_type`, …) are ignored unless you filter upstream (e.g. a **VIEW** that only exposes solar-related rows).

**Bootstrap schema:** apply [`migrations/001_wasted_sun_qh_daily.sql`](migrations/001_wasted_sun_qh_daily.sql) for the default mart and `wasted_sun_sync_meta` (freshness via `last_success_at`).

## Aggregation rules

1. **Same-day merge:** All rows with the same `date_day` are merged by **summing** each `qh_*_mwh` bucket independently.
2. **Day total (MWh) in storage:** Algebraic sum of merged quarter-hour values (signed).
3. **Day total (MWh) on the site:** **Absolute value** of that net — headline KPIs, share text, and household analogy show positive “wasted” magnitude.
4. **Chart:** Quarter-hours are rolled into **24 hourly** bars with **signed** values (negative = waste in source convention; positive or near-zero = less or no waste in that hour): qh 1–4 → hour 0, 5–8 → hour 1, …, 93–96 → hour 23. Values in **qh_97–qh_100** (if present) are **added to hour 23** so the full day’s energy appears in the profile.
5. **Headline “per hour”:** Headline day total MWh ÷ 24 (not the mean of signed hourly bars).
6. **YTD:** `SELECT COALESCE(SUM(ABS(total_mwh)),0) … WHERE date_day BETWEEN Jan-1 AND selected_day`.
7. **Euros:** After sync, **`qh_*_eur`** and **`total_eur`** come from peninsula **OMIE wholesale €/MWh** (`PriceEspEurMwh` in Cube). The app uses those when **`WASTED_SUN_EUR_PER_MWH`** is unset or zero. Set **`WASTED_SUN_EUR_PER_MWH` &gt; 0** only to override with a single flat €/MWh. **YTD €** uses `SUM(ABS(total_eur))` unless the flat rate is set (`YTD MWh × rate`). Apply [`migrations/002_wasted_sun_qh_eur.sql`](migrations/002_wasted_sun_qh_eur.sql) and re-sync after upgrading.

8. **Day total vs YTD:** **`total_mwh`** in the table should match the algebraic sum of **`qh_*`**. The **headline** uses **`ABS(total_mwh)`**; **YTD** sums those absolute daily values. If `total_mwh` drifts from the qh sum, KPIs will look inconsistent—fix upstream or re-sync.

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

## Cube.js (`WastedEnergy` cube) — ETL source only (production)

**Production:** the public site reads **Postgres only**. Cube is used by the daily sync job
(`wasted-sun-sync`) to materialize rows into `wasted_sun_qh_daily`. Do not set `CUBE_API_*` on
the web component.

For local debugging you may still set `WASTED_SUN_DATA_SOURCE=cube` to query Cube live.

The sync job and optional live mode use the **fixed** public `WastedEnergy` semantic model
(dimensions only; schema does not change on the Cube side):

| Member | Role |
| ------ | ---- |
| `WastedEnergy.DateDay` | Calendar day (`YYYY-MM-DD` string) |
| `WastedEnergy.QuarterPeriod` | 1-based quarter-hour index (1 … `WASTED_SUN_PG_QH_SLOTS`) |
| `WastedEnergy.EnergyMwh` | MWh for that period |
| `WastedEnergy.PriceEspEurMwh` | OMIE peninsula wholesale €/MWh for that row |

**Wasted-sun scope:** Not every redispatch/restriction row is unused solar. Set at least one of:

- `WASTED_SUN_CUBE_REDISPATCH_CODES` — comma-separated `RedispatchCode` allowlist
- `WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES` — comma-separated `RestrictionTypeCode` allowlist

When both are set, lists are combined with **OR** (row matches if its `RedispatchCode` is in the
first list **or** its `RestrictionTypeCode` is in the second). Applied to
day, YTD, earliest-date, and `as_of` queries. Other dimensions (`EnergyConcept`,
`RedispatchDirection`, descriptions, `PricePtEurMwh`, …) are not used.

**Day chart:** rows for one `DateDay` are pivoted by `QuarterPeriod` (summing `EnergyMwh` and
`EnergyMwh × PriceEspEurMwh` when multiple rows share a period), then rolled into 24 hourly
bars using the same rules as Postgres qh columns.

**EUR:** If `WASTED_SUN_EUR_PER_MWH` is set and &gt; 0, that flat rate is used (Postgres parity).
Otherwise EUR comes from per-row `PriceEspEurMwh` in Cube.

**YTD / bounds:** By default **`WASTED_SUN_CUBE_SKIP_YTD=true`** so pages stay within HTTP
timeouts (YTD needs a full-year row scan without Cube measures). Set to `false` to enable
monthly parallel YTD loads with **`WASTED_SUN_CUBE_YTD_TIMEOUT_SEC`** (default 20). Bounds use
fast `limit: 1` queries on `DateDay`; `/` and **Latest** use **max** `DateDay`.

## Mock mode

Without `DATABASE_URL` or `CUBE_API_URL`, or with `USE_MOCK_DATA=true`, the app uses fixtures
and ignores the Postgres schema.
