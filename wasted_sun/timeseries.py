"""Quarter-hourly columns (qh_*_mwh) merged into hourly display buckets."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Sequence
from zoneinfo import ZoneInfo

from wasted_sun.models import HourlyPoint
from wasted_sun.waste_display import (
    headline_waste_eur,
    headline_waste_eur_from_net,
    headline_waste_mwh,
    net_mwh_from_qh,
)

# Default pipeline width (must match qh_N_mwh column count when not overridden).
QH_SLOTS = 100


def qh_column_names(n: int = QH_SLOTS) -> tuple[str, ...]:
    return tuple(f"qh_{i}_mwh" for i in range(1, n + 1))


def qh_eur_column_names(n: int = QH_SLOTS) -> tuple[str, ...]:
    return tuple(f"qh_{i}_eur" for i in range(1, n + 1))


def _merge_qh_columns(rows: Sequence[dict], keys: tuple[str, ...], n_slots: int) -> list[Decimal]:
    """Sum qh_* columns when multiple rows exist for the same date_day."""
    acc = [Decimal("0")] * n_slots
    for row in rows:
        lower = {str(k).lower(): v for k, v in row.items()}
        for i, key in enumerate(keys):
            v = row.get(key)
            if v is None:
                v = lower.get(key.lower())
            if v is not None:
                try:
                    acc[i] += Decimal(str(v))
                except (InvalidOperation, ValueError):
                    pass
    return acc


def merge_qh_across_rows(rows: Sequence[dict], n_slots: int = QH_SLOTS) -> list[Decimal]:
    return _merge_qh_columns(rows, qh_column_names(n_slots), n_slots)


def merge_qh_eur_across_rows(rows: Sequence[dict], n_slots: int = QH_SLOTS) -> list[Decimal]:
    return _merge_qh_columns(rows, qh_eur_column_names(n_slots), n_slots)


def hourly_mwh_from_qh(qh: Sequence[Decimal], n_slots: int = QH_SLOTS) -> list[Decimal]:
    """
    Build 24 hourly MWh values from quarter-hourly series.
    Uses the first 96 slots for hours 0–23 (four quarter-hours each).
    Any slots with index >= 96 (up to n_slots) are added to hour 23.
    """
    series = list(qh[:n_slots])
    pad_to = max(n_slots, 96)
    series.extend([Decimal("0")] * max(0, pad_to - len(series)))

    hours: list[Decimal] = []
    for h in range(24):
        chunk = series[h * 4 : h * 4 + 4]
        if len(chunk) < 4:
            chunk = chunk + [Decimal("0")] * (4 - len(chunk))
        hours.append(sum(chunk, start=Decimal("0")))

    if len(series) > 96:
        hours[23] += sum(series[96:n_slots], start=Decimal("0"))

    return hours


def qh_series_to_hourly_points(
    day: date,
    qh: Sequence[Decimal],
    tz: ZoneInfo,
    eur_per_mwh: Decimal | None,
    n_slots: int = QH_SLOTS,
) -> tuple[tuple[HourlyPoint, ...], Decimal, Decimal]:
    """Return signed hourly points and positive headline day MWh/EUR totals."""
    hourly_mwh = hourly_mwh_from_qh(qh, n_slots=n_slots)
    day_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz)
    rate = eur_per_mwh if eur_per_mwh is not None else Decimal("0")
    points: list[HourlyPoint] = []
    for h, mwh in enumerate(hourly_mwh):
        ts = day_start + timedelta(hours=h)
        eur = (mwh * rate).quantize(Decimal("0.01")) if rate else Decimal("0")
        points.append(HourlyPoint(bucket_start=ts, mwh_unused=mwh, eur_waste=eur))
    net = net_mwh_from_qh(qh, n_slots) if qh else Decimal("0")
    day_total_mwh = headline_waste_mwh(net)
    day_total_eur = headline_waste_eur(net, eur_per_mwh)
    return tuple(points), day_total_mwh, day_total_eur


def qh_mwh_eur_to_hourly_points(
    day: date,
    qh_mwh: Sequence[Decimal],
    qh_eur: Sequence[Decimal],
    tz: ZoneInfo,
    n_slots: int = QH_SLOTS,
) -> tuple[tuple[HourlyPoint, ...], Decimal, Decimal]:
    """Signed hourly MWh/EUR from stored qh slots (Cube PriceEspEurMwh parity)."""
    hourly_mwh = hourly_mwh_from_qh(qh_mwh, n_slots=n_slots)
    hourly_eur_vals = hourly_mwh_from_qh(qh_eur, n_slots=n_slots)
    day_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz)
    points: list[HourlyPoint] = []
    for h, mwh in enumerate(hourly_mwh):
        ts = day_start + timedelta(hours=h)
        eur = hourly_eur_vals[h].quantize(Decimal("0.01"))
        points.append(HourlyPoint(bucket_start=ts, mwh_unused=mwh, eur_waste=eur))
    net_mwh = net_mwh_from_qh(qh_mwh, n_slots)
    net_eur = sum(qh_eur[:n_slots], start=Decimal("0"))
    return (
        tuple(points),
        headline_waste_mwh(net_mwh),
        headline_waste_eur_from_net(net_eur),
    )
