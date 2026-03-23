"""Quarter-hourly columns (qh_*_mwh) merged into hourly display buckets."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence
from zoneinfo import ZoneInfo

from wasted_sun.models import HourlyPoint

# Pipeline delivers up to 100 quarter-hour slots per calendar day.
QH_SLOTS = 100


def qh_column_names(n: int = QH_SLOTS) -> tuple[str, ...]:
    return tuple(f"qh_{i}_mwh" for i in range(1, n + 1))


def merge_qh_across_rows(rows: Sequence[dict], n_slots: int = QH_SLOTS) -> list[Decimal]:
    """Sum qh_* columns when multiple rows exist for the same date_day."""
    acc = [Decimal("0")] * n_slots
    keys = qh_column_names(n_slots)
    for row in rows:
        for i, key in enumerate(keys):
            v = row.get(key)
            if v is not None:
                acc[i] += Decimal(str(v))
    return acc


def hourly_mwh_from_qh(qh: Sequence[Decimal]) -> list[Decimal]:
    """
    Build 24 hourly MWh values from quarter-hourly series.
    Uses qh_1..qh_96 for hours 0–23; any qh_97..qh_100 spill into the last hour.
    """
    padded = list(qh[:QH_SLOTS]) + [Decimal("0")] * max(0, QH_SLOTS - len(qh))
    hours: list[Decimal] = []
    for h in range(24):
        chunk = padded[h * 4 : h * 4 + 4]
        hours.append(sum(chunk, start=Decimal("0")))
    if len(padded) > 96:
        hours[23] += sum(padded[96:QH_SLOTS], start=Decimal("0"))
    return hours


def qh_series_to_hourly_points(
    day: date,
    qh: Sequence[Decimal],
    tz: ZoneInfo,
    eur_per_mwh: Decimal | None,
) -> tuple[tuple[HourlyPoint, ...], Decimal, Decimal]:
    """Return hourly points, day total MWh, day total EUR (EUR optional via rate)."""
    hourly_mwh = hourly_mwh_from_qh(qh)
    day_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz)
    rate = eur_per_mwh if eur_per_mwh is not None else Decimal("0")
    points: list[HourlyPoint] = []
    for h, mwh in enumerate(hourly_mwh):
        ts = day_start + timedelta(hours=h)
        eur = (mwh * rate).quantize(Decimal("0.01")) if rate else Decimal("0")
        points.append(HourlyPoint(bucket_start=ts, mwh_unused=mwh, eur_waste=eur))
    day_total_mwh = sum(qh, start=Decimal("0")) if qh else Decimal("0")
    day_total_eur = (day_total_mwh * rate).quantize(Decimal("0.01")) if rate else Decimal("0")
    return tuple(points), day_total_mwh, day_total_eur
