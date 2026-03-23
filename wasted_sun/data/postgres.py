from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from wasted_sun.models import (
    DailyMetrics,
    DayNotFoundError,
    HourlyPoint,
    aggregate_hourly,
    mean_hourly_from_totals,
)


class PostgresMetricsProvider:
    """Read-only hourly rows from PostgreSQL; schema driven by env (see DATA_CONTRACT.md)."""

    def __init__(
        self,
        dsn: str,
        timezone: ZoneInfo,
        table: str,
        col_ts: str,
        col_mwh: str,
        col_eur: str,
        as_of_query: str | None,
    ) -> None:
        self._dsn = dsn
        self._tz = timezone
        self._table = table
        self._col_ts = col_ts
        self._col_mwh = col_mwh
        self._col_eur = col_eur
        self._as_of_query = as_of_query

    def _identifiers(self) -> tuple[sql.SQL, sql.SQL, sql.SQL, sql.SQL]:
        return (
            sql.Identifier(self._table),
            sql.Identifier(self._col_ts),
            sql.Identifier(self._col_mwh),
            sql.Identifier(self._col_eur),
        )

    def _earliest_from_conn(self, conn: psycopg.Connection) -> date:
        table, col_ts, _, _ = self._identifiers()
        q = sql.SQL("SELECT MIN({ts}) AS t FROM {tbl}").format(ts=col_ts, tbl=table)
        with conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
        if not row or row[0] is None:
            raise RuntimeError("wasted_sun: Postgres table is empty or MIN(ts) is NULL")
        t = row[0]
        if t.tzinfo is None:
            t = t.replace(tzinfo=self._tz)
        return t.astimezone(self._tz).date()

    def earliest_date(self) -> date:
        with psycopg.connect(self._dsn) as conn:
            return self._earliest_from_conn(conn)

    def _madrid_day_bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=self._tz)
        end = start + timedelta(days=1)
        return start, end

    def _fetch_hourly(self, conn: psycopg.Connection, start: datetime, end: datetime) -> list[HourlyPoint]:
        table, col_ts, col_mwh, col_eur = self._identifiers()
        q = sql.SQL(
            "SELECT {ts} AS ts, {mwh} AS mwh, {eur} AS eur FROM {tbl} "
            "WHERE {ts} >= %s AND {ts} < %s ORDER BY {ts}"
        ).format(ts=col_ts, mwh=col_mwh, eur=col_eur, tbl=table)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (start, end))
            rows = cur.fetchall()
        points: list[HourlyPoint] = []
        for r in rows:
            ts = r["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=self._tz)
            else:
                ts = ts.astimezone(self._tz)
            points.append(
                HourlyPoint(
                    bucket_start=ts,
                    mwh_unused=Decimal(str(r["mwh"])),
                    eur_waste=Decimal(str(r["eur"])),
                )
            )
        return points

    def _fetch_ytd(self, conn: psycopg.Connection, through: date) -> tuple[Decimal, Decimal]:
        y_start = datetime(through.year, 1, 1, 0, 0, tzinfo=self._tz)
        _, y_end = self._madrid_day_bounds(through)
        y_end_exclusive = y_end
        table, col_ts, col_mwh, col_eur = self._identifiers()
        q = sql.SQL(
            "SELECT COALESCE(SUM({mwh}), 0) AS mwh, COALESCE(SUM({eur}), 0) AS eur FROM {tbl} "
            "WHERE {ts} >= %s AND {ts} < %s"
        ).format(mwh=col_mwh, eur=col_eur, ts=col_ts, tbl=table)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (y_start, y_end_exclusive))
            row = cur.fetchone()
        assert row is not None
        return Decimal(str(row["mwh"])), Decimal(str(row["eur"]))

    def _fetch_as_of(self, conn: psycopg.Connection) -> datetime:
        if self._as_of_query:
            with conn.cursor() as cur:
                cur.execute(self._as_of_query)
                row = cur.fetchone()
            if row and row[0] is not None:
                v = row[0]
                if isinstance(v, datetime):
                    if v.tzinfo is None:
                        return v.replace(tzinfo=self._tz)
                    return v.astimezone(self._tz)
        table, col_ts, _, _ = self._identifiers()
        q = sql.SQL("SELECT MAX({ts}) FROM {tbl}").format(ts=col_ts, tbl=table)
        with conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
        if not row or row[0] is None:
            return datetime.now(self._tz)
        v = row[0]
        if v.tzinfo is None:
            return v.replace(tzinfo=self._tz)
        return v.astimezone(self._tz)

    def get_daily_metrics(self, day: date) -> DailyMetrics:
        today = datetime.now(self._tz).date()
        if day > today:
            raise DayNotFoundError(day)
        start, end = self._madrid_day_bounds(day)
        with psycopg.connect(self._dsn) as conn:
            earliest = self._earliest_from_conn(conn)
            hourly = self._fetch_hourly(conn, start, end)
            if not hourly:
                raise DayNotFoundError(day)
            ytd_mwh, ytd_eur = self._fetch_ytd(conn, day)
            as_of = self._fetch_as_of(conn)

        day_mwh, day_eur = aggregate_hourly(hourly)
        n = len(hourly)
        mean_mwh, mean_eur = mean_hourly_from_totals(day_mwh, day_eur, n)

        return DailyMetrics(
            day=day,
            hourly=tuple(hourly),
            day_total_mwh=day_mwh,
            day_total_eur=day_eur,
            ytd_mwh=ytd_mwh,
            ytd_eur=ytd_eur,
            mean_hourly_mwh=mean_mwh,
            mean_hourly_eur=mean_eur,
            as_of=as_of,
            earliest_available_date=earliest,
        )
