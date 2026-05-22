"""Load day and boundary data from Cube for sync."""

from __future__ import annotations

import logging
from datetime import date

from wasted_sun.data.cube import CubeClient
from wasted_sun.data.cube_scope import (
    D_DATE,
    D_MWH,
    D_PERIOD,
    D_PRICE_ESP,
    wasted_sun_filters,
)

logger = logging.getLogger(__name__)


class CubeSyncLoader:
    def __init__(
        self,
        api_url: str,
        api_token: str,
        *,
        redispatch_codes: tuple[str, ...],
        restriction_type_codes: tuple[str, ...],
        http_timeout_sec: int = 90,
    ) -> None:
        if not redispatch_codes and not restriction_type_codes:
            raise ValueError(
                "Set WASTED_SUN_CUBE_REDISPATCH_CODES and/or "
                "WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES"
            )
        self._client = CubeClient(api_url, api_token, timeout_sec=http_timeout_sec)
        self._redispatch_codes = redispatch_codes
        self._restriction_type_codes = restriction_type_codes

    def _scope(self) -> list:
        return wasted_sun_filters(self._redispatch_codes, self._restriction_type_codes)

    def load_day_rows(self, day: date) -> list[dict]:
        logger.info("sync cube load_day_rows day=%s", day)
        return self._client.load(
            {
                "dimensions": [D_DATE, D_PERIOD, D_MWH, D_PRICE_ESP],
                "filters": [
                    {
                        "member": D_DATE,
                        "operator": "equals",
                        "values": [day.isoformat()],
                    },
                    *self._scope(),
                ],
                "order": {D_PERIOD: "asc"},
                "limit": 50_000,
            }
        )

    def _boundary_date(self, *, ascending: bool) -> date | None:
        order = "asc" if ascending else "desc"
        rows = self._client.load(
            {
                "dimensions": [D_DATE],
                "filters": self._scope(),
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

    def fetch_earliest_latest(self) -> tuple[date, date]:
        earliest = self._boundary_date(ascending=True)
        latest = self._boundary_date(ascending=False)
        if earliest is None or latest is None:
            raise RuntimeError("wasted_sun sync: Cube WastedEnergy has no DateDay values")
        return earliest, latest
