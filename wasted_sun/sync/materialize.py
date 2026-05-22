"""Build wide Postgres rows from Cube long-format day rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from wasted_sun.data.cube import merge_cube_rows
from wasted_sun.timeseries import qh_column_names


def day_row_from_cube_rows(
    day: date,
    rows: list[dict],
    *,
    n_slots: int,
) -> dict | None:
    """
    Pivot Cube rows into one wide row for wasted_sun_qh_daily.
    Returns None when there is no energy data for the day.
    """
    if not rows:
        return None
    qh_mwh, _ = merge_cube_rows(rows, n_slots)
    total_mwh = sum(qh_mwh[:n_slots], start=Decimal("0"))
    if total_mwh == 0 and not any(qh_mwh[:n_slots]):
        return None
    out: dict = {"date_day": day, "total_mwh": total_mwh}
    for key, val in zip(qh_column_names(n_slots), qh_mwh[:n_slots], strict=True):
        out[key] = val
    return out
