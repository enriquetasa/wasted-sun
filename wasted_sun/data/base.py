from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from flask import Flask

from wasted_sun.exceptions import ConfigurationError
from wasted_sun.models import DailyMetrics
from wasted_sun.sql_guard import parse_cube_code_list


class MetricsProvider(Protocol):
    """Loads peninsula solar-waste metrics for the public site."""

    def earliest_date(self) -> date: ...

    def get_daily_metrics(self, day: date) -> DailyMetrics: ...


def _cube_provider(cfg, *, api_url: str, token: str, eur, qh_slots: int):
    from wasted_sun.data.cube import CubeMetricsProvider

    try:
        redispatch = parse_cube_code_list(
            cfg.get("CUBE_REDISPATCH_CODES") or "",
            label="WASTED_SUN_CUBE_REDISPATCH_CODES",
        )
        restriction = parse_cube_code_list(
            cfg.get("CUBE_RESTRICTION_TYPE_CODES") or "",
            label="WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES",
        )
    except ValueError as e:
        raise ConfigurationError(str(e)) from e
    try:
        return CubeMetricsProvider(
            api_url=api_url,
            api_token=token,
            timezone=cfg["TIMEZONE"],
            eur_per_mwh=eur,
            redispatch_codes=redispatch,
            restriction_type_codes=restriction,
            qh_slots=qh_slots,
        )
    except ValueError as e:
        raise ConfigurationError(str(e)) from e


def get_provider(app: Flask):
    from wasted_sun.data.cube import CubeMetricsProvider
    from wasted_sun.data.mock import MockMetricsProvider
    from wasted_sun.data.postgres import PostgresMetricsProvider

    cfg = app.config
    use_mock = cfg.get("USE_MOCK_DATA")
    dsn = cfg.get("DATABASE_URL")
    cube_url = (cfg.get("CUBE_API_URL") or "").strip()
    data_source = (cfg.get("DATA_SOURCE") or "").strip().lower()
    eur = cfg.get("EUR_PER_MWH")
    try:
        qh_slots = int(cfg.get("PG_QH_SLOTS", 100))
    except (ValueError, TypeError) as e:
        raise ConfigurationError(f"PG_QH_SLOTS must be an integer: {e}") from e
    if use_mock:
        return MockMetricsProvider(
            timezone=cfg["TIMEZONE"],
            eur_per_mwh=eur,
            qh_slots=qh_slots,
        )
    if data_source == "cube":
        token = (cfg.get("CUBE_API_TOKEN") or "").strip()
        if not cube_url or not token:
            raise ConfigurationError(
                "Cube mode requires CUBE_API_URL and CUBE_API_TOKEN."
            )
        return _cube_provider(cfg, api_url=cube_url, token=token, eur=eur, qh_slots=qh_slots)
    if data_source == "postgres":
        if not dsn:
            raise ConfigurationError(
                "Postgres mode requires DATABASE_URL (WASTED_SUN_DATA_SOURCE=postgres)."
            )
    elif cube_url and not dsn:
        token = (cfg.get("CUBE_API_TOKEN") or "").strip()
        if not token:
            raise ConfigurationError("Cube mode requires CUBE_API_TOKEN.")
        return _cube_provider(cfg, api_url=cube_url, token=token, eur=eur, qh_slots=qh_slots)
    if not dsn:
        return MockMetricsProvider(
            timezone=cfg["TIMEZONE"],
            eur_per_mwh=eur,
            qh_slots=qh_slots,
        )
    try:
        return PostgresMetricsProvider(
            dsn=dsn,
            timezone=cfg["TIMEZONE"],
            table=cfg["PG_TABLE"],
            date_col=cfg["PG_COL_DATE_DAY"],
            total_mwh_col=cfg["PG_COL_TOTAL_MWH"],
            as_of_query=cfg.get("PG_AS_OF_QUERY") or None,
            as_of_meta_table=cfg.get("PG_AS_OF_META_TABLE") or None,
            as_of_meta_column=cfg.get("PG_AS_OF_META_COLUMN") or None,
            eur_per_mwh=eur,
            qh_slots=qh_slots,
        )
    except (ValueError, KeyError) as e:
        raise ConfigurationError(str(e)) from e
