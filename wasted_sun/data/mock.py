from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo

from wasted_sun.models import DailyMetrics, DayNotFoundError, mean_hourly_from_totals
from wasted_sun.timeseries import QH_SLOTS, qh_series_to_hourly_points


def _pseudo_unit_interval(seed: bytes) -> float:
    h = hashlib.sha256(seed).digest()
    return int.from_bytes(h[:8], "big") / float(2**64)


@lru_cache(maxsize=64)
def _cached_ytd(
    year: int,
    end: date,
    earliest: date,
    tz: ZoneInfo,
    eur_per_mwh: Decimal | None,
    qh_slots: int,
) -> tuple[Decimal, Decimal]:
    """Accumulate mock YTD totals; cached because the loop is O(days-in-year)."""
    d = date(year, 1, 1)
    if d < earliest:
        d = earliest
    total_mwh = Decimal("0")
    total_eur = Decimal("0")
    while d <= end:
        seed = f"wasted-sun-mock-{d.isoformat()}".encode()
        qh: list[Decimal] = []
        for i in range(qh_slots):
            hour_float = (i * 15) / 60.0
            s = seed + f"-qh{i}".encode()
            u1 = _pseudo_unit_interval(s)
            hour_angle = abs(hour_float - 13.5) / 13.5
            shape = max(0.0, 1.0 - hour_angle**1.3)
            qh.append(Decimal(str(round((0.012 + 0.09 * shape) * (0.5 + u1), 5))))
        _, dm, de = qh_series_to_hourly_points(d, qh, tz, eur_per_mwh, n_slots=qh_slots)
        total_mwh += dm
        total_eur += de
        d += timedelta(days=1)
    return total_mwh, total_eur


class MockMetricsProvider:
    """Deterministic quarter-hourly fixtures rolled up to hourly chart bars."""

    def __init__(
        self,
        timezone: ZoneInfo,
        eur_per_mwh: Decimal | None,
        qh_slots: int = QH_SLOTS,
    ) -> None:
        self._tz = timezone
        self._eur_per_mwh = eur_per_mwh
        self._qh_slots = qh_slots
        self._earliest = date(2024, 1, 1)

    def earliest_date(self) -> date:
        return self._earliest

    def latest_available_date(self) -> date:
        return datetime.now(self._tz).date()

    def _day_seed(self, day: date) -> bytes:
        return f"wasted-sun-mock-{day.isoformat()}".encode()

    def _qh_for_day(self, day: date) -> list[Decimal]:
        if day < self._earliest:
            raise DayNotFoundError(day)
        if day > self.latest_available_date():
            raise DayNotFoundError(day)

        qh: list[Decimal] = []
        for i in range(self._qh_slots):
            slot_minutes = i * 15
            hour_float = slot_minutes / 60.0
            seed = self._day_seed(day) + f"-qh{i}".encode()
            u1 = _pseudo_unit_interval(seed)
            hour_angle = abs(hour_float - 13.5) / 13.5
            shape = max(0.0, 1.0 - hour_angle**1.3)
            mwh = Decimal(str(round((0.012 + 0.09 * shape) * (0.5 + u1), 5)))
            qh.append(mwh)
        return qh

    def _ytd_totals(self, through: date) -> tuple[Decimal, Decimal]:
        today = datetime.now(self._tz).date()
        end = min(through, today)
        return _cached_ytd(
            through.year, end, self._earliest,
            self._tz, self._eur_per_mwh, self._qh_slots,
        )

    def get_daily_metrics(self, day: date) -> DailyMetrics:
        qh = self._qh_for_day(day)
        hourly, day_mwh, day_eur = qh_series_to_hourly_points(
            day, qh, self._tz, self._eur_per_mwh, n_slots=self._qh_slots
        )
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
            latest_available_date=self.latest_available_date(),
        )
