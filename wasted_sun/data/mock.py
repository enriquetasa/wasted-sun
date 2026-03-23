from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from wasted_sun.models import (
    DailyMetrics,
    DayNotFoundError,
    HourlyPoint,
    aggregate_hourly,
    mean_hourly_from_totals,
)


def _pseudo_unit_interval(seed: bytes) -> float:
    h = hashlib.sha256(seed).digest()
    return int.from_bytes(h[:8], "big") / float(2**64)


class MockMetricsProvider:
    """Deterministic hourly fixtures; no database required."""

    def __init__(self, timezone: ZoneInfo) -> None:
        self._tz = timezone
        self._earliest = date(2024, 1, 1)

    def earliest_date(self) -> date:
        return self._earliest

    def _day_seed(self, day: date) -> bytes:
        return f"wasted-sun-mock-{day.isoformat()}".encode()

    def _hourly_for_day(self, day: date) -> tuple[HourlyPoint, ...]:
        if day < self._earliest:
            raise DayNotFoundError(day)
        today = datetime.now(self._tz).date()
        if day > today:
            raise DayNotFoundError(day)

        points: list[HourlyPoint] = []
        day_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=self._tz)
        for h in range(24):
            ts = day_start + timedelta(hours=h)
            seed = self._day_seed(day) + f"-{h}".encode()
            u1 = _pseudo_unit_interval(seed)
            u2 = _pseudo_unit_interval(seed + b"mwh")
            # Solar-ish profile: more waste midday
            hour_angle = abs(h - 13.5) / 13.5
            shape = max(0.0, 1.0 - hour_angle**1.3)
            mwh = Decimal(str(round((0.05 + 0.35 * shape) * (0.5 + u1), 4)))
            eur = (mwh * Decimal(str(round(35 + 25 * u2, 2)))).quantize(Decimal("0.01"))
            points.append(HourlyPoint(bucket_start=ts, mwh_unused=mwh, eur_waste=eur))
        return tuple(points)

    def _ytd_totals(self, through: date) -> tuple[Decimal, Decimal]:
        start = date(through.year, 1, 1)
        d = start
        total_mwh = Decimal("0")
        total_eur = Decimal("0")
        today = datetime.now(self._tz).date()
        while d <= through and d <= today and d >= self._earliest:
            hourly = self._hourly_for_day(d)
            dm, de = aggregate_hourly(hourly)
            total_mwh += dm
            total_eur += de
            d += timedelta(days=1)
        return total_mwh, total_eur

    def get_daily_metrics(self, day: date) -> DailyMetrics:
        hourly = self._hourly_for_day(day)
        day_mwh, day_eur = aggregate_hourly(hourly)
        n = len(hourly)
        mean_mwh, mean_eur = mean_hourly_from_totals(day_mwh, day_eur, n)
        ytd_mwh, ytd_eur = self._ytd_totals(day)

        as_of = datetime.now(self._tz).replace(minute=0, second=0, microsecond=0)

        return DailyMetrics(
            day=day,
            hourly=hourly,
            day_total_mwh=day_mwh,
            day_total_eur=day_eur,
            ytd_mwh=ytd_mwh,
            ytd_eur=ytd_eur,
            mean_hourly_mwh=mean_mwh,
            mean_hourly_eur=mean_eur,
            as_of=as_of,
            earliest_available_date=self._earliest,
        )
