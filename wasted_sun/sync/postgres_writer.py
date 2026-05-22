"""Upsert materialized rows into Postgres."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql

from wasted_sun.sql_guard import validate_pg_identifier, validate_pg_qualified_table
from wasted_sun.timeseries import qh_column_names, qh_eur_column_names

logger = logging.getLogger(__name__)

_META_TABLE = "wasted_sun_sync_meta"
_META_ID = 1


def _qualified_identifier(name: str) -> sql.Identifier:
    parts = name.split(".")
    return sql.Identifier(*parts)


class PostgresSyncWriter:
    def __init__(
        self,
        dsn: str,
        *,
        table: str,
        date_col: str = "date_day",
        n_slots: int = 100,
        meta_table: str = _META_TABLE,
        tz: ZoneInfo | None = None,
    ) -> None:
        self._dsn = dsn
        self._table = validate_pg_qualified_table(table, label="WASTED_SUN_PG_TABLE")
        self._date_col = validate_pg_identifier(date_col, label="WASTED_SUN_PG_COL_DATE_DAY")
        self._qh_mwh_keys = qh_column_names(n_slots)
        self._qh_eur_keys = qh_eur_column_names(n_slots)
        self._meta_table = validate_pg_qualified_table(meta_table, label="sync meta table")
        self._tz = tz or ZoneInfo("Europe/Madrid")

    def upsert_day(self, conn: psycopg.Connection, row: dict[str, Any]) -> None:
        tbl = _qualified_identifier(self._table)
        dc = sql.Identifier(self._date_col)
        cols: list[sql.Identifier | sql.SQL] = [dc]
        cols.extend(sql.Identifier(k) for k in self._qh_mwh_keys)
        cols.extend(sql.Identifier(k) for k in self._qh_eur_keys)
        cols.append(sql.Identifier("total_mwh"))
        cols.append(sql.Identifier("total_eur"))
        cols.append(sql.Identifier("synced_at"))

        placeholders = sql.SQL(", ").join(sql.Placeholder() * len(cols))
        col_names = sql.SQL(", ").join(cols)
        update_keys = (*self._qh_mwh_keys, *self._qh_eur_keys)
        updates = sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(k)) for k in update_keys
        )
        updates = sql.SQL(
            "{updates}, total_mwh = EXCLUDED.total_mwh, total_eur = EXCLUDED.total_eur, "
            "synced_at = EXCLUDED.synced_at"
        ).format(updates=updates)

        q = sql.SQL(
            "INSERT INTO {tbl} ({cols}) VALUES ({ph}) "
            "ON CONFLICT ({dc}) DO UPDATE SET {upd}"
        ).format(
            tbl=tbl,
            cols=col_names,
            ph=placeholders,
            dc=dc,
            upd=updates,
        )

        day = row["date_day"]
        values: list[Any] = [day]
        for k in self._qh_mwh_keys:
            values.append(row[k])
        for k in self._qh_eur_keys:
            values.append(row[k])
        values.append(row["total_mwh"])
        values.append(row["total_eur"])
        values.append(datetime.now(self._tz))

        with conn.cursor() as cur:
            cur.execute(q, values)

    def record_success(
        self,
        conn: psycopg.Connection,
        *,
        last_day: date,
        days_upserted: int,
    ) -> None:
        q = sql.SQL(
            "UPDATE {meta} SET last_success_at = %s, last_day_synced = %s, "
            "days_upserted = %s, error_message = NULL WHERE id = %s"
        ).format(meta=_qualified_identifier(self._meta_table))
        now = datetime.now(self._tz)
        with conn.cursor() as cur:
            cur.execute(q, (now, last_day, days_upserted, _META_ID))

    def record_failure(self, conn: psycopg.Connection, message: str) -> None:
        q = sql.SQL(
            "UPDATE {meta} SET error_message = %s WHERE id = %s"
        ).format(meta=_qualified_identifier(self._meta_table))
        with conn.cursor() as cur:
            cur.execute(q, (message[:2000], _META_ID))
