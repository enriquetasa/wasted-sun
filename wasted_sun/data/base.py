from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from flask import Flask

from wasted_sun.models import DailyMetrics


class MetricsProvider(Protocol):
    """Loads peninsula solar-waste metrics for the public site."""

    def earliest_date(self) -> date: ...

    def get_daily_metrics(self, day: date) -> DailyMetrics: ...


def get_provider(app: Flask):
    from wasted_sun.data.mock import MockMetricsProvider
    from wasted_sun.data.postgres import PostgresMetricsProvider

    cfg = app.config
    use_mock = cfg.get("USE_MOCK_DATA")
    dsn = cfg.get("DATABASE_URL")
    eur = cfg.get("EUR_PER_MWH")
    qh_slots = int(cfg.get("PG_QH_SLOTS", 100))
    if use_mock or not dsn:
        return MockMetricsProvider(
            timezone=cfg["TIMEZONE"],
            eur_per_mwh=eur,
            qh_slots=qh_slots,
        )
    return PostgresMetricsProvider(
        dsn=dsn,
        timezone=cfg["TIMEZONE"],
        table=cfg["PG_TABLE"],
        date_col=cfg["PG_COL_DATE_DAY"],
        total_mwh_col=cfg["PG_COL_TOTAL_MWH"],
        as_of_query=cfg.get("PG_AS_OF_QUERY") or None,
        eur_per_mwh=eur,
        qh_slots=qh_slots,
    )
