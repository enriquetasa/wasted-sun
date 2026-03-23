# Data contract (PostgreSQL)

The app expects **one or more rows per `date_day`**, each with up to **100 quarter-hourly MWh columns** (`qh_1_mwh` … `qh_100_mwh`) plus metadata. This matches wide exports such as i3dia-style daily tables.

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

Optional SQL: `WASTED_SUN_PG_AS_OF_QUERY` returning one `timestamptz` / `timestamp`. Otherwise the app uses **end of `MAX(date_day)`** in Europe/Madrid.

## Table name

Set `WASTED_SUN_PG_TABLE` to your table or **VIEW** name (default in config: `wasted_sun_qh_daily`).

## Mock mode

Without `DATABASE_URL`, or with `USE_MOCK_DATA=true`, the app uses fixtures and ignores this schema.
