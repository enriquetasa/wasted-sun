"""Cube.js WastedEnergy cube (fixed schema: dimensions only, no measures)."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from wasted_sun.models import DailyMetrics, DayNotFoundError, HourlyPoint, mean_hourly_from_totals
from wasted_sun.timeseries import hourly_mwh_from_qh, qh_series_to_hourly_points

logger = logging.getLogger(__name__)

# Fixed public WastedEnergy semantic layer (schema does not change).
CUBE = "WastedEnergy"
D_DATE = f"{CUBE}.DateDay"
D_PERIOD = f"{CUBE}.QuarterPeriod"
D_MWH = f"{CUBE}.EnergyMwh"
D_PRICE_ESP = f"{CUBE}.PriceEspEurMwh"
D_REDISPATCH = f"{CUBE}.RedispatchCode"
D_RESTRICTION = f"{CUBE}.RestrictionTypeCode"

_DEFAULT_QH_SLOTS = 100
_LOAD_PATH = "/cubejs-api/v1/load"
_DEFAULT_TIMEOUT_SEC = 90
_CONTINUE_WAIT_MAX = 20
_CONTINUE_WAIT_SLEEP_SEC = 1.0
_YTD_MONTH_WORKERS = 6


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _period_index(row: dict, n_slots: int) -> int | None:
    raw = row.get(D_PERIOD)
    if raw is None:
        return None
    try:
        period = int(raw)
    except (TypeError, ValueError):
        return None
    if period < 1 or period > n_slots:
        return None
    return period - 1


def merge_cube_rows(
    rows: list[dict],
    n_slots: int,
) -> tuple[list[Decimal], list[Decimal]]:
    """
    Pivot long Cube rows into per-slot MWh and EUR (EUR = sum of mwh * PriceEspEurMwh).
    Multiple rows per QuarterPeriod are summed (same as Postgres qh merge).
    """
    qh_mwh = [Decimal("0")] * n_slots
    qh_eur = [Decimal("0")] * n_slots
    for row in rows:
        i = _period_index(row, n_slots)
        if i is None:
            continue
        mwh = _decimal(row.get(D_MWH))
        price = _decimal(row.get(D_PRICE_ESP))
        qh_mwh[i] += mwh
        if mwh and price:
            qh_eur[i] += (mwh * price).quantize(Decimal("0.00001"))
    return qh_mwh, qh_eur


def _hourly_points_from_slots(
    day: date,
    qh_mwh: list[Decimal],
    qh_eur: list[Decimal],
    tz: ZoneInfo,
    n_slots: int,
) -> tuple[tuple[HourlyPoint, ...], Decimal, Decimal]:
    hourly_mwh = hourly_mwh_from_qh(qh_mwh, n_slots=n_slots)
    hourly_eur_vals = hourly_mwh_from_qh(qh_eur, n_slots=n_slots)
    day_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz)
    points: list[HourlyPoint] = []
    for h, mwh in enumerate(hourly_mwh):
        ts = day_start + timedelta(hours=h)
        eur = hourly_eur_vals[h].quantize(Decimal("0.01"))
        points.append(HourlyPoint(bucket_start=ts, mwh_unused=mwh, eur_waste=eur))
    day_mwh = sum(qh_mwh[:n_slots], start=Decimal("0"))
    day_eur = sum(qh_eur[:n_slots], start=Decimal("0")).quantize(Decimal("0.01"))
    return tuple(points), day_mwh, day_eur


class CubeClient:
    def __init__(
        self, api_url: str, api_token: str, *, timeout_sec: int = _DEFAULT_TIMEOUT_SEC
    ) -> None:
        base = api_url.rstrip("/")
        self._load_url = f"{base}{_LOAD_PATH}"
        self._token = api_token.strip()
        self._timeout = timeout_sec

    def load(
        self,
        query: dict[str, Any],
        *,
        max_continue_wait: int = _CONTINUE_WAIT_MAX,
    ) -> list[dict]:
        body = json.dumps({"query": query}).encode("utf-8")
        # Cube REST docs use Authorization: TOKEN (raw secret). Prefix "Bearer " in
        # CUBE_API_TOKEN yourself only if your deployment requires it.
        req = Request(
            self._load_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": self._token,
            },
        )
        dims = ",".join(query.get("dimensions") or [])
        t0 = time.perf_counter()
        for attempt in range(max_continue_wait):
            try:
                with urlopen(req, timeout=self._timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:500]
                logger.warning(
                    "cube load HTTP %s dims=%s attempt=%d elapsed_ms=%d",
                    e.code,
                    dims,
                    attempt + 1,
                    int((time.perf_counter() - t0) * 1000),
                )
                raise RuntimeError(f"Cube API HTTP {e.code}: {detail}") from e
            except URLError as e:
                logger.warning(
                    "cube load unreachable dims=%s attempt=%d elapsed_ms=%d err=%s",
                    dims,
                    attempt + 1,
                    int((time.perf_counter() - t0) * 1000),
                    e,
                )
                raise RuntimeError(f"Cube API unreachable: {e}") from e

            err = payload.get("error")
            if err == "Continue wait":
                logger.info(
                    "cube load continue-wait dims=%s attempt=%d/%d elapsed_ms=%d",
                    dims,
                    attempt + 1,
                    max_continue_wait,
                    int((time.perf_counter() - t0) * 1000),
                )
                if attempt + 1 >= max_continue_wait:
                    raise RuntimeError("Cube API still processing after continue-wait retries")
                time.sleep(_CONTINUE_WAIT_SLEEP_SEC)
                continue
            if err:
                logger.warning(
                    "cube load error dims=%s err=%s elapsed_ms=%d",
                    dims,
                    err,
                    int((time.perf_counter() - t0) * 1000),
                )
                raise RuntimeError(f"Cube API error: {err}")
            data = payload.get("data")
            if not isinstance(data, list):
                raise RuntimeError("Cube API response missing data array")
            logger.info(
                "cube load ok dims=%s rows=%d attempts=%d elapsed_ms=%d",
                dims,
                len(data),
                attempt + 1,
                int((time.perf_counter() - t0) * 1000),
            )
            return data
        raise RuntimeError("Cube API continue-wait loop exhausted")


def _month_ranges(y0: date, through: date) -> list[tuple[date, date]]:
    """Inclusive month chunks from y0 through through."""
    ranges: list[tuple[date, date]] = []
    y, m = y0.year, y0.month
    end_y, end_m = through.year, through.month
    while (y, m) <= (end_y, end_m):
        start = date(y, m, 1)
        if m == 12:
            month_end = date(y, 12, 31)
        else:
            month_end = date(y, m + 1, 1) - timedelta(days=1)
        ranges.append((max(y0, start), min(through, month_end)))
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return ranges


class CubeMetricsProvider:
    """Read-only metrics from the fixed WastedEnergy Cube.js model."""

    def __init__(
        self,
        api_url: str,
        api_token: str,
        timezone: ZoneInfo,
        eur_per_mwh: Decimal | None,
        redispatch_codes: tuple[str, ...],
        restriction_type_codes: tuple[str, ...],
        qh_slots: int = _DEFAULT_QH_SLOTS,
        http_timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
        skip_ytd: bool = True,
        ytd_timeout_sec: int = 20,
    ) -> None:
        if qh_slots < 1 or qh_slots > 200:
            raise ValueError("qh_slots must be between 1 and 200")
        if not redispatch_codes and not restriction_type_codes:
            raise ValueError(
                "Set WASTED_SUN_CUBE_REDISPATCH_CODES and/or "
                "WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES to the codes that mean wasted sun"
            )
        self._client = CubeClient(api_url, api_token, timeout_sec=http_timeout_sec)
        self._tz = timezone
        self._eur_per_mwh = eur_per_mwh
        self._qh_slots = qh_slots
        self._redispatch_codes = redispatch_codes
        self._restriction_type_codes = restriction_type_codes
        self._earliest: date | None = None
        self._latest: date | None = None
        self._ytd_cache: dict[tuple[int, str], tuple[Decimal, Decimal]] = {}
        self._skip_ytd = skip_ytd
        self._ytd_timeout_sec = ytd_timeout_sec

    def _wasted_sun_filters(self) -> list[dict[str, Any]]:
        """Row matches if RedispatchCode OR RestrictionTypeCode is in the allowlists."""
        clauses: list[dict[str, Any]] = []
        if self._redispatch_codes:
            clauses.append(
                {
                    "member": D_REDISPATCH,
                    "operator": "equals",
                    "values": list(self._redispatch_codes),
                }
            )
        if self._restriction_type_codes:
            clauses.append(
                {
                    "member": D_RESTRICTION,
                    "operator": "equals",
                    "values": list(self._restriction_type_codes),
                }
            )
        if len(clauses) == 1:
            return clauses
        return [{"or": clauses}]

    def _load_day_rows(self, day: date) -> list[dict]:
        return self._client.load(
            {
                "dimensions": [D_DATE, D_PERIOD, D_MWH, D_PRICE_ESP],
                "filters": [
                    {
                        "member": D_DATE,
                        "operator": "equals",
                        "values": [day.isoformat()],
                    },
                    *self._wasted_sun_filters(),
                ],
                "order": {D_PERIOD: "asc"},
                "limit": 50_000,
            }
        )

    def _load_rows_between(self, start: date, end: date) -> list[dict]:
        use_flat = self._eur_per_mwh is not None and self._eur_per_mwh > 0
        dims = [D_DATE, D_MWH] if use_flat else [D_DATE, D_MWH, D_PRICE_ESP]
        return self._client.load(
            {
                "dimensions": dims,
                "filters": [
                    {"member": D_DATE, "operator": "gte", "values": [start.isoformat()]},
                    {"member": D_DATE, "operator": "lte", "values": [end.isoformat()]},
                    *self._wasted_sun_filters(),
                ],
                "limit": 100_000,
            },
            max_continue_wait=12,
        )

    def _boundary_date(self, *, ascending: bool) -> date | None:
        order = "asc" if ascending else "desc"
        rows = self._client.load(
            {
                "dimensions": [D_DATE],
                "filters": self._wasted_sun_filters(),
                "order": {D_DATE: order},
                "limit": 1,
            },
            max_continue_wait=8,
        )
        if not rows:
            return None
        raw = rows[0].get(D_DATE)
        if raw is None:
            return None
        if isinstance(raw, date):
            return raw
        return date.fromisoformat(str(raw)[:10])

    def _ensure_earliest(self) -> date:
        if self._earliest is not None:
            return self._earliest
        d = self._boundary_date(ascending=True)
        if d is None:
            raise RuntimeError("wasted_sun: Cube WastedEnergy has no DateDay values")
        self._earliest = d
        return d

    def earliest_date(self) -> date:
        return self._ensure_earliest()

    def _ensure_latest(self) -> date:
        if self._latest is not None:
            return self._latest
        d = self._boundary_date(ascending=False)
        if d is None:
            raise RuntimeError("wasted_sun: Cube WastedEnergy has no DateDay values")
        self._latest = d
        return d

    def latest_available_date(self) -> date:
        return self._ensure_latest()

    def _sum_rows_mwh_eur(self, rows: list[dict]) -> tuple[Decimal, Decimal]:
        total_mwh = Decimal("0")
        total_eur = Decimal("0")
        use_flat = self._eur_per_mwh is not None and self._eur_per_mwh > 0
        for row in rows:
            mwh = _decimal(row.get(D_MWH))
            total_mwh += mwh
            if use_flat:
                total_eur += mwh * self._eur_per_mwh  # type: ignore[operator]
            else:
                price = _decimal(row.get(D_PRICE_ESP))
                if mwh and price:
                    total_eur += mwh * price
        return total_mwh, total_eur.quantize(Decimal("0.01"))

    def _ytd_mwh_eur(self, through: date) -> tuple[Decimal, Decimal]:
        if self._skip_ytd:
            return Decimal("0"), Decimal("0")
        key = (through.year, through.isoformat())
        if key in self._ytd_cache:
            return self._ytd_cache[key]
        y0 = date(through.year, 1, 1)
        chunks = _month_ranges(y0, through)
        all_rows: list[dict] = []
        try:
            with ThreadPoolExecutor(max_workers=min(_YTD_MONTH_WORKERS, len(chunks))) as pool:
                futures = [pool.submit(self._load_rows_between, s, e) for s, e in chunks]
                for fut in as_completed(futures, timeout=self._ytd_timeout_sec):
                    all_rows.extend(fut.result())
        except Exception as e:
            logger.warning(
                "Cube YTD incomplete or timed out after %ss (%s); showing zero YTD",
                self._ytd_timeout_sec,
                e,
            )
            return Decimal("0"), Decimal("0")
        totals = self._sum_rows_mwh_eur(all_rows)
        self._ytd_cache[key] = totals
        return totals

    def _as_of_from_date(self, d: date | None) -> datetime:
        if d is None:
            return datetime.now(self._tz)
        return datetime.combine(d, dt_time(23, 59, 59), tzinfo=self._tz)

    def get_daily_metrics(self, day: date) -> DailyMetrics:
        t0 = time.perf_counter()
        earliest = self._ensure_earliest()
        latest = self._ensure_latest()
        if day < earliest or day > latest:
            raise DayNotFoundError(day)

        rows = self._load_day_rows(day)
        logger.info(
            "cube get_daily_metrics bounds day=%s skip_ytd=%s day_rows=%d bounds_ms=%d",
            day,
            self._skip_ytd,
            len(rows),
            int((time.perf_counter() - t0) * 1000),
        )
        if not rows:
            raise DayNotFoundError(day)

        ytd_mwh, ytd_eur = self._ytd_mwh_eur(day)
        as_of = self._as_of_from_date(latest)

        qh_mwh, qh_eur_slots = merge_cube_rows(rows, self._qh_slots)
        use_flat = self._eur_per_mwh is not None and self._eur_per_mwh > 0

        if use_flat:
            hourly, day_mwh, day_eur = qh_series_to_hourly_points(
                day, qh_mwh, self._tz, self._eur_per_mwh, n_slots=self._qh_slots
            )
            if self._eur_per_mwh and self._eur_per_mwh > 0:
                ytd_eur = (ytd_mwh * self._eur_per_mwh).quantize(Decimal("0.01"))
        else:
            hourly, day_mwh, day_eur = _hourly_points_from_slots(
                day, qh_mwh, qh_eur_slots, self._tz, self._qh_slots
            )

        n = len(hourly)
        mean_mwh, mean_eur = mean_hourly_from_totals(day_mwh, day_eur, n)

        logger.info(
            "cube get_daily_metrics done day=%s total_ms=%d",
            day,
            int((time.perf_counter() - t0) * 1000),
        )

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
            earliest_available_date=earliest,
            latest_available_date=latest,
        )
