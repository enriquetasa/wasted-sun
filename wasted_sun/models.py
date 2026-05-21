from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class HourlyPoint:
    """One hour of peninsula solar waste (unused PV energy)."""

    bucket_start: datetime  # timezone-aware (Europe/Madrid)
    mwh_unused: Decimal
    eur_waste: Decimal


@dataclass(frozen=True)
class DailyMetrics:
    """Aggregates for one calendar day (Madrid) plus YTD rollups."""

    day: date
    hourly: tuple[HourlyPoint, ...]
    day_total_mwh: Decimal
    day_total_eur: Decimal
    ytd_mwh: Decimal
    ytd_eur: Decimal
    mean_hourly_mwh: Decimal
    mean_hourly_eur: Decimal
    as_of: datetime
    earliest_available_date: date
    latest_available_date: date


def mean_hourly_from_totals(total_mwh: Decimal, total_eur: Decimal, n_hours: int) -> tuple[Decimal, Decimal]:
    if n_hours <= 0:
        return Decimal("0"), Decimal("0")
    n = Decimal(n_hours)
    return total_mwh / n, total_eur / n


class DayNotFoundError(Exception):
    def __init__(self, day: date, message: str = "No data for this date") -> None:
        self.day = day
        super().__init__(message)
