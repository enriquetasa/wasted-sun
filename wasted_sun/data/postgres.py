from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from wasted_sun.models import DailyMetrics, DayNotFoundError
from wasted_sun.waste_display import mean_hourly_waste_from_headline
from wasted_sun.sql_guard import (
    validate_as_of_select,
    validate_pg_identifier,
    validate_pg_qualified_table,
    validate_qh_slots,
)
from wasted_sun.timeseries import (
    merge_qh_across_rows,
    merge_qh_eur_across_rows,
    qh_mwh_eur_to_hourly_points,
    qh_series_to_hourly_points,
)


def _qualified_sql_identifier(qualified_name: str) -> sql.Identifier:
    parts = qualified_name.split(".")
    return sql.Identifier(*parts)


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
        total_eur_col: str,
        as_of_query: str | None,
        as_of_meta_table: str | None,
        as_of_meta_column: str | None,
        eur_per_mwh: Decimal | None,
        qh_slots: int = 100,
    ) -> None:
        self._dsn = dsn
        self._tz = timezone
        self._table = validate_pg_qualified_table(table, label="WASTED_SUN_PG_TABLE")
        self._date_col = validate_pg_identifier(date_col, label="WASTED_SUN_PG_COL_DATE_DAY")
        self._total_mwh_col = validate_pg_identifier(
            total_mwh_col, label="WASTED_SUN_PG_COL_TOTAL_MWH"
        )
        self._total_eur_col = validate_pg_identifier(
            total_eur_col, label="WASTED_SUN_PG_COL_TOTAL_EUR"
        )
        self._qh_slots = validate_qh_slots(qh_slots)
        self._eur_per_mwh = eur_per_mwh

        self._as_of_meta_table: str | None = None
        self._as_of_meta_column: str | None = None
        self._as_of_query: str | None = None

        mt = (as_of_meta_table or "").strip()
        mc = (as_of_meta_column or "").strip()
        aq = (as_of_query or "").strip() if as_of_query else ""

        if mt or mc:
            if not mt or not mc:
                raise ValueError(
                    "Set both as_of_meta_table and as_of_meta_column, or neither"
                )
            self._as_of_meta_table = validate_pg_qualified_table(
                mt, label="WASTED_SUN_PG_AS_OF_META_TABLE"
            )
            self._as_of_meta_column = validate_pg_identifier(
                mc, label="WASTED_SUN_PG_AS_OF_META_COLUMN"
            )
            if aq:
                raise ValueError(
                    "Do not set WASTED_SUN_PG_AS_OF_QUERY together with meta as_of table/column"
                )
        elif aq:
            self._as_of_query = validate_as_of_select(aq)

    def _tbl(self) -> sql.Identifier:
        return _qualified_sql_identifier(self._table)

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

    def _latest_from_conn(self, conn: psycopg.Connection) -> date:
        q = sql.SQL("SELECT MAX({dc}) AS d FROM {tbl}").format(dc=self._dc(), tbl=self._tbl())
        with conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
        if not row or row[0] is None:
            raise RuntimeError("wasted_sun: Postgres table is empty or MAX(date) is NULL")
        v = row[0]
        if isinstance(v, datetime):
            return v.astimezone(self._tz).date()
        return v

    def latest_available_date(self) -> date:
        with psycopg.connect(self._dsn) as conn:
            return self._latest_from_conn(conn)

    def _fetch_rows_for_day(self, conn: psycopg.Connection, day: date) -> list[dict]:
        q = sql.SQL("SELECT * FROM {tbl} WHERE {dc} = %s").format(tbl=self._tbl(), dc=self._dc())
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (day,))
            return list(cur.fetchall())

    def _fetch_ytd_mwh(self, conn: psycopg.Connection, through: date) -> Decimal:
        y0 = date(through.year, 1, 1)
        tm = sql.Identifier(self._total_mwh_col)
        q = sql.SQL(
            "SELECT COALESCE(SUM(ABS({tm})), 0) AS s FROM {tbl} "
            "WHERE {dc} >= %s AND {dc} <= %s"
        ).format(tm=tm, tbl=self._tbl(), dc=self._dc())
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (y0, through))
            row = cur.fetchone()
        assert row is not None
        return Decimal(str(row["s"]))

    def _fetch_ytd_eur(self, conn: psycopg.Connection, through: date) -> Decimal:
        y0 = date(through.year, 1, 1)
        te = sql.Identifier(self._total_eur_col)
        q = sql.SQL(
            "SELECT COALESCE(SUM(ABS({te})), 0) AS s FROM {tbl} "
            "WHERE {dc} >= %s AND {dc} <= %s"
        ).format(te=te, tbl=self._tbl(), dc=self._dc())
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, (y0, through))
            row = cur.fetchone()
        assert row is not None
        return Decimal(str(row["s"])).quantize(Decimal("0.01"))

    def _uses_flat_eur_rate(self) -> bool:
        return self._eur_per_mwh is not None and self._eur_per_mwh > 0

    def _fetch_as_of(self, conn: psycopg.Connection) -> datetime:
        if self._as_of_meta_table and self._as_of_meta_column:
            t = _qualified_sql_identifier(self._as_of_meta_table)
            c = sql.Identifier(self._as_of_meta_column)
            q = sql.SQL("SELECT MAX({c}) AS ts FROM {t}").format(c=c, t=t)
            with conn.cursor() as cur:
                cur.execute(q)
                row = cur.fetchone()
            if row and row[0] is not None:
                v = row[0]
                if isinstance(v, datetime):
                    if v.tzinfo is None:
                        return v.replace(tzinfo=self._tz)
                    return v.astimezone(self._tz)
                if isinstance(v, date):
                    return datetime.combine(v, time(23, 59, 59), tzinfo=self._tz)

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
        with psycopg.connect(self._dsn) as conn:
            latest = self._latest_from_conn(conn)
            if day > latest:
                raise DayNotFoundError(day)
            earliest = self._earliest_from_conn(conn)
            rows = self._fetch_rows_for_day(conn, day)
            if not rows:
                raise DayNotFoundError(day)
            ytd_mwh = self._fetch_ytd_mwh(conn, day)
            as_of = self._fetch_as_of(conn)
            if self._uses_flat_eur_rate():
                ytd_eur = (ytd_mwh * self._eur_per_mwh).quantize(Decimal("0.01"))  # type: ignore[operator]
            else:
                ytd_eur = self._fetch_ytd_eur(conn, day)

        qh_mwh = merge_qh_across_rows(rows, self._qh_slots)
        qh_eur = merge_qh_eur_across_rows(rows, self._qh_slots)
        if self._uses_flat_eur_rate():
            hourly, day_mwh, day_eur = qh_series_to_hourly_points(
                day, qh_mwh, self._tz, self._eur_per_mwh, n_slots=self._qh_slots
            )
        elif any(qh_eur):
            hourly, day_mwh, day_eur = qh_mwh_eur_to_hourly_points(
                day, qh_mwh, qh_eur, self._tz, n_slots=self._qh_slots
            )
        else:
            hourly, day_mwh, day_eur = qh_series_to_hourly_points(
                day, qh_mwh, self._tz, None, n_slots=self._qh_slots
            )
        n = len(hourly)
        mean_mwh, mean_eur = mean_hourly_waste_from_headline(day_mwh, day_eur, n)

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
            latest_available_date=latest,
        )
