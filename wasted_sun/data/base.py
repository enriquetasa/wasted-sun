from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from flask import Flask

from wasted_sun.models import DailyMetrics


class MetricsProvider(Protocol):
    """Loads peninsula hourly solar-waste metrics for the public site."""

    def earliest_date(self) -> date: ...

    def get_daily_metrics(self, day: date) -> DailyMetrics: ...


def get_provider(app: Flask) -> MetricsProvider:
    from wasted_sun.data.mock import MockMetricsProvider
    from wasted_sun.data.postgres import PostgresMetricsProvider

    cfg = app.config
    use_mock = cfg.get("USE_MOCK_DATA")
    dsn = cfg.get("DATABASE_URL")
    if use_mock or not dsn:
        return MockMetricsProvider(timezone=cfg["TIMEZONE"])
    return PostgresMetricsProvider(
        dsn=dsn,
        timezone=cfg["TIMEZONE"],
        table=cfg["PG_TABLE"],
        col_ts=cfg["PG_COL_TS"],
        col_mwh=cfg["PG_COL_MWH"],
        col_eur=cfg["PG_COL_EUR"],
        as_of_query=cfg.get("PG_AS_OF_QUERY") or None,
    )
