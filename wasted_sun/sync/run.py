"""CLI: materialize Cube WastedEnergy into Postgres."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from wasted_sun.sql_guard import parse_cube_code_list
from wasted_sun.sync.cube_loader import CubeSyncLoader
from wasted_sun.sync.materialize import day_row_from_cube_rows
from wasted_sun.sync.postgres_writer import PostgresSyncWriter

logger = logging.getLogger(__name__)


def _parse_day(s: str) -> date:
    return date.fromisoformat(s)


def _iter_days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _resolve_range(
    args: argparse.Namespace,
    loader: CubeSyncLoader,
) -> tuple[date, date]:
    if args.full:
        return loader.fetch_earliest_latest()
    if args.date_from and args.date_to:
        start, end = _parse_day(args.date_from), _parse_day(args.date_to)
        if start > end:
            raise ValueError("--from must be on or before --to")
        return start, end
    latest = loader.fetch_earliest_latest()[1]
    days = max(1, int(args.days))
    start = latest - timedelta(days=days - 1)
    return start, latest


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(raw)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sync Cube WastedEnergy data into Postgres")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="Backfill earliest..latest from Cube")
    mode.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="Range start (inclusive)")
    p.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="Range end (inclusive, with --from)")
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="Rolling window ending at latest Cube day (default: 7)",
    )
    p.add_argument("--dry-run", action="store_true", help="Fetch and log only; no Postgres writes")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    args = build_parser().parse_args(argv)
    if args.date_from and not args.date_to:
        print("error: --to is required when --from is set", file=sys.stderr)
        return 2

    cube_url = (os.environ.get("CUBE_API_URL") or "").strip()
    cube_token = (os.environ.get("CUBE_API_TOKEN") or "").strip()
    if not cube_url or not cube_token:
        logger.error("CUBE_API_URL and CUBE_API_TOKEN are required for sync")
        return 1

    dsn = (os.environ.get("WASTED_SUN_SYNC_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not dsn and not args.dry_run:
        logger.error("DATABASE_URL or WASTED_SUN_SYNC_DATABASE_URL is required")
        return 1

    try:
        redispatch = parse_cube_code_list(
            os.environ.get("WASTED_SUN_CUBE_REDISPATCH_CODES") or "",
            label="WASTED_SUN_CUBE_REDISPATCH_CODES",
        )
        restriction = parse_cube_code_list(
            os.environ.get("WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES") or "",
            label="WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES",
        )
    except ValueError as e:
        logger.error("%s", e)
        return 1

    tz = ZoneInfo(os.environ.get("APP_TIMEZONE", "Europe/Madrid"))
    qh_slots = _env_int("WASTED_SUN_PG_QH_SLOTS", 100)
    table = os.environ.get("WASTED_SUN_PG_TABLE", "wasted_sun_qh_daily").strip()
    timeout = _env_int("WASTED_SUN_CUBE_HTTP_TIMEOUT_SEC", 90)

    loader = CubeSyncLoader(
        cube_url,
        cube_token,
        redispatch_codes=redispatch,
        restriction_type_codes=restriction,
        http_timeout_sec=timeout,
    )

    try:
        start, end = _resolve_range(args, loader)
    except (ValueError, RuntimeError) as e:
        logger.error("sync range failed: %s", e)
        return 1

    logger.info("sync range %s .. %s dry_run=%s", start, end, args.dry_run)

    writer: PostgresSyncWriter | None = None
    if not args.dry_run:
        writer = PostgresSyncWriter(dsn, table=table, n_slots=qh_slots, tz=tz)

    upserted = 0
    skipped = 0
    failed = 0
    last_ok_day: date | None = None

    import psycopg

    try:
        with psycopg.connect(dsn) if writer else _null_context() as conn:
            for day in _iter_days(start, end):
                t0 = time.perf_counter()
                try:
                    rows = loader.load_day_rows(day)
                    wide = day_row_from_cube_rows(day, rows, n_slots=qh_slots)
                    if wide is None:
                        skipped += 1
                        logger.info("sync skip empty day=%s cube_rows=%d", day, len(rows))
                        continue
                    if writer:
                        writer.upsert_day(conn, wide)
                        conn.commit()
                    upserted += 1
                    last_ok_day = day
                    logger.info(
                        "sync ok day=%s total_mwh=%s cube_rows=%d ms=%d",
                        day,
                        wide["total_mwh"],
                        len(rows),
                        int((time.perf_counter() - t0) * 1000),
                    )
                except Exception:
                    failed += 1
                    logger.exception("sync failed day=%s", day)
                    if writer and conn:
                        conn.rollback()
                        writer.record_failure(conn, f"failed on {day.isoformat()}")
                        conn.commit()

            if writer and conn and last_ok_day is not None and failed == 0:
                writer.record_success(
                    conn,
                    last_day=last_ok_day,
                    days_upserted=upserted,
                )
                conn.commit()
    except Exception:
        logger.exception("sync database connection failed")
        return 1

    logger.info(
        "sync done upserted=%d skipped=%d failed=%d range=%s..%s",
        upserted,
        skipped,
        failed,
        start,
        end,
    )
    return 1 if failed else 0


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
