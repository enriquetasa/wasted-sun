from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from wasted_sun.models import DailyMetrics, DayNotFoundError, mean_hourly_from_totals
from wasted_sun.timeseries import merge_qh_across_rows, qh_series_to_hourly_points


class PostgresMetricsProvider:
    """
    Read-only rows keyed by date_day with qh_1_mwh … qh_N_mwh (quarter-hourly MWh).
    See DATA_CONTRACT.md.
    """

    def __init__(
        self,
        dsn: str,
        timezone: ZoneInfo,
        table: str,
        date_col: str,
        total_mwh_col: str,
        as_of_query: str | None,
        eur_per_mwh: Decimal | None,
        qh_slots: int = 100,
    ) -> None:
        self._dsn = dsn
        self._tz = timezone
        self._table = table
        self._date_col = date_col
        self._total_mwh_col = total_mwh_col
        self._as_of_query = as_of_query
        self._eur_per_mwh = eur_per_mwh
        self._qh_slots = qh_slots

    def _tbl(self) -> sql.Identifier:
        return sql.Identifier(self._table)

    def _dc(self) -> sql.Identifier:
        return sql.Identifier(self._date_col)

    def _earliest_from_conn(self, conn: psycopg.Connection) -> date:
        q = sql.SQL("SELECT MIN({dc}) AS d FROM {tbl}").format(dc=self._dc(), tbl=self._tbl())
        with conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
        if not row or row[0] is None:
            raise RuntimeError("wasted_sun: Postgres table is empty or MIN(date) is NULL")
        v = row[0]
        if isinstance(v, datetime):
            return v.astimezone(self._tz).date()
        return v

    def earliest_date(self) -> date:
        with psycopg.connect(self._dsn) as conn:
            return self._earliest_from_conn(conn)

    def _fetch_rows_for_day(self, conn: psycopg.Connection, day: date) -> list[dict]:
        q = sql.SQL("SELECT * FROM {tbl} WHERE {dc} = %s").format(tbl=self._tbl(), dc=self._dc())
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (day,))
            return list(cur.fetchall())

    def _fetch_ytd_mwh(self, conn: psycopg.Connection, through: date) -> Decimal:
        y0 = date(through.year, 1, 1)
        tm = sql.Identifier(self._total_mwh_col)
        q = sql.SQL(
            "SELECT COALESCE(SUM({tm}), 0) AS s FROM {tbl} "
            "WHERE {dc} >= %s AND {dc} <= %s"
        ).format(tm=tm, tbl=self._tbl(), dc=self._dc())
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (y0, through))
            row = cur.fetchone()
        assert row is not None
        return Decimal(str(row["s"]))

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
                if isinstance(v, date):
                    return datetime.combine(v, time(23, 59, 59), tzinfo=self._tz)

        q = sql.SQL("SELECT MAX({dc}) AS d FROM {tbl}").format(dc=self._dc(), tbl=self._tbl())
        with conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
        if not row or row[0] is None:
            return datetime.now(self._tz)
        d = row[0]
        if isinstance(d, datetime):
            d = d.astimezone(self._tz).date()
        return datetime.combine(d, time(23, 59, 59), tzinfo=self._tz)

    def get_daily_metrics(self, day: date) -> DailyMetrics:
        today = datetime.now(self._tz).date()
        if day > today:
            raise DayNotFoundError(day)

        with psycopg.connect(self._dsn) as conn:
            earliest = self._earliest_from_conn(conn)
            rows = self._fetch_rows_for_day(conn, day)
            if not rows:
                raise DayNotFoundError(day)
            ytd_mwh = self._fetch_ytd_mwh(conn, day)
            as_of = self._fetch_as_of(conn)

        qh = merge_qh_across_rows(rows, self._qh_slots)
        hourly, day_mwh_from_qh, day_eur_from_qh = qh_series_to_hourly_points(
            day, qh, self._tz, self._eur_per_mwh, n_slots=self._qh_slots
        )

        # Prefer summed quarter-hours for the headline day total; YTD uses total_mwh from SQL.
        day_mwh = day_mwh_from_qh
        ytd_eur = (
            (ytd_mwh * self._eur_per_mwh).quantize(Decimal("0.01"))
            if self._eur_per_mwh and self._eur_per_mwh > 0
            else Decimal("0")
        )

        day_eur = day_eur_from_qh
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
