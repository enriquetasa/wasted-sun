import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from wasted_sun.data.base import get_provider
from wasted_sun.data.cube import (
    D_DATE,
    D_MWH,
    D_PERIOD,
    D_PRICE_ESP,
    CubeClient,
    CubeMetricsProvider,
    _month_ranges,
    cube_load_url,
    merge_cube_rows,
)
from wasted_sun.exceptions import ConfigurationError
from wasted_sun.models import DayNotFoundError


def test_merge_cube_rows_sums_periods_and_eur():
    rows = [
        {D_PERIOD: 1, D_MWH: 1, D_PRICE_ESP: 10},
        {D_PERIOD: 1, D_MWH: 2, D_PRICE_ESP: 10},
        {D_PERIOD: 2, D_MWH: 0.5, D_PRICE_ESP: 20},
    ]
    mwh, eur = merge_cube_rows(rows, n_slots=2)
    assert mwh[0] == Decimal("3")
    assert mwh[1] == Decimal("0.5")
    assert eur[0] == Decimal("30.00000")
    assert eur[1] == Decimal("10.00000")


def _fake_urlopen_factory(responses: list[dict]):
    calls: list[dict] = []

    def fake_urlopen(req, timeout=0):
        calls.append(json.loads(req.data.decode())["query"])
        payload = responses.pop(0)
        return BytesIO(json.dumps(payload).encode())

    return fake_urlopen, calls


def test_cube_provider_daily_and_ytd(monkeypatch):
    day = date(2024, 6, 15)
    responses = [
        {"data": [{D_DATE: "2024-01-01"}]},
        {"data": [{D_DATE: "2024-06-15"}]},
        {
            "data": [
                {D_DATE: "2024-06-15", D_PERIOD: 1, D_MWH: 1, D_PRICE_ESP: 50},
                {D_DATE: "2024-06-15", D_PERIOD: 2, D_MWH: 2, D_PRICE_ESP: 50},
            ]
        },
    ]
    fake, calls = _fake_urlopen_factory(responses)
    tz = ZoneInfo("Europe/Madrid")
    with patch("wasted_sun.data.cube.urlopen", fake):
        prov = CubeMetricsProvider(
            api_url="https://cube.example",
            api_token="secret",
            timezone=tz,
            eur_per_mwh=None,
            redispatch_codes=("RD1",),
            restriction_type_codes=(),
            qh_slots=2,
            skip_ytd=False,
        )
        with patch.object(prov, "_ytd_mwh_eur", return_value=(Decimal("10"), Decimal("500.00"))):
            metrics = prov.get_daily_metrics(day)

    assert metrics.day_total_mwh == Decimal("3")
    assert metrics.day_total_eur == Decimal("150.00")
    assert metrics.ytd_mwh == Decimal("10")
    assert metrics.ytd_eur == Decimal("500.00")
    assert len(metrics.hourly) == 24
    day_query = next(
        c for c in calls if c["filters"][0]["member"] == D_DATE and c["filters"][0]["operator"] == "equals"
    )
    assert day_query["filters"][0]["values"] == ["2024-06-15"]
    assert {
        "member": "WastedEnergy.RedispatchCode",
        "operator": "equals",
        "values": ["RD1"],
    } in day_query["filters"]


def test_cube_scope_or_when_both_lists():
    tz = ZoneInfo("Europe/Madrid")
    responses = [
        {"data": [{D_DATE: "2024-01-01"}]},
        {"data": [{D_DATE: "2024-06-15"}]},
        {"data": [{D_DATE: "2024-06-15", D_PERIOD: 1, D_MWH: 1, D_PRICE_ESP: 1}]},
        {"data": []},
    ]
    fake, calls = _fake_urlopen_factory(responses)
    with patch("wasted_sun.data.cube.urlopen", fake):
        prov = CubeMetricsProvider(
            api_url="https://cube.example",
            api_token="secret",
            timezone=tz,
            eur_per_mwh=None,
            redispatch_codes=("RD1",),
            restriction_type_codes=("RT9",),
        )
        prov.get_daily_metrics(date(2024, 6, 15))

    day_query = next(c for c in calls if D_PERIOD in c.get("dimensions", []))
    scope = [f for f in day_query["filters"] if "or" in f or f.get("member", "").startswith("WastedEnergy.R")]
    assert len(scope) == 1
    assert scope[0]["or"] == [
        {
            "member": "WastedEnergy.RedispatchCode",
            "operator": "equals",
            "values": ["RD1"],
        },
        {
            "member": "WastedEnergy.RestrictionTypeCode",
            "operator": "equals",
            "values": ["RT9"],
        },
    ]


def test_cube_provider_empty_day():
    responses = [
        {"data": [{D_DATE: "2024-01-01"}]},
        {"data": [{D_DATE: "2024-06-15"}]},
        {"data": []},
    ]
    fake, _ = _fake_urlopen_factory(responses)
    with patch("wasted_sun.data.cube.urlopen", fake):
        prov = CubeMetricsProvider(
            api_url="https://cube.example",
            api_token="secret",
            timezone=ZoneInfo("Europe/Madrid"),
            eur_per_mwh=None,
            redispatch_codes=("RD1",),
            restriction_type_codes=("RT1",),
        )
        with pytest.raises(DayNotFoundError):
            prov.get_daily_metrics(date(2024, 6, 15))


def test_month_ranges_splits_year():
    assert _month_ranges(date(2024, 1, 1), date(2024, 3, 15)) == [
        (date(2024, 1, 1), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 15)),
    ]


def test_cube_skip_ytd_by_default():
    prov = CubeMetricsProvider(
        api_url="https://cube.example",
        api_token="secret",
        timezone=ZoneInfo("Europe/Madrid"),
        eur_per_mwh=None,
        redispatch_codes=("RD1",),
        restriction_type_codes=(),
        skip_ytd=True,
    )
    assert prov._ytd_mwh_eur(date(2024, 6, 15)) == (Decimal("0"), Decimal("0"))


def test_cube_provider_requires_scope_codes():
    with pytest.raises(ValueError, match="WASTED_SUN_CUBE"):
        CubeMetricsProvider(
            api_url="https://cube.example",
            api_token="secret",
            timezone=ZoneInfo("Europe/Madrid"),
            eur_per_mwh=None,
            redispatch_codes=(),
            restriction_type_codes=(),
        )


def test_get_provider_requires_cube_credentials(app):
    app.config["USE_MOCK_DATA"] = False
    app.config["DATA_SOURCE"] = "cube"
    app.config["CUBE_API_URL"] = "https://cube.example"
    app.config["CUBE_API_TOKEN"] = ""
    with pytest.raises(ConfigurationError):
        get_provider(app)


def test_cube_load_url_host_root():
    assert (
        cube_load_url("https://cube.example")
        == "https://cube.example/cubejs-api/v1/load"
    )


def test_cube_load_url_already_has_api_prefix():
    assert (
        cube_load_url("https://data-serving.example/cubejs-api/v1")
        == "https://data-serving.example/cubejs-api/v1/load"
    )


def test_cube_load_url_already_full_load_path():
    url = "https://cube.example/cubejs-api/v1/load"
    assert cube_load_url(url) == url


def test_cube_client_retries_continue_wait():
    responses = [
        {"error": "Continue wait"},
        {"data": [{D_DATE: "2024-01-01"}]},
    ]
    fake, _ = _fake_urlopen_factory(responses)
    with patch("wasted_sun.data.cube.urlopen", fake):
        rows = CubeClient("https://cube.example", "secret").load({"dimensions": [D_DATE]})
    assert rows == [{D_DATE: "2024-01-01"}]


def test_get_provider_both_urls_prefers_postgres(app):
    app.config["USE_MOCK_DATA"] = False
    app.config["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
    app.config["CUBE_API_URL"] = "https://cube.example"
    app.config["CUBE_API_TOKEN"] = "tok"
    prov = get_provider(app)
    assert prov.__class__.__name__ == "PostgresMetricsProvider"


def test_get_provider_picks_cube_when_url_set(app):
    app.config["USE_MOCK_DATA"] = False
    app.config["DATABASE_URL"] = ""
    app.config["CUBE_API_URL"] = "https://cube.example"
    app.config["CUBE_API_TOKEN"] = "tok"
    app.config["CUBE_REDISPATCH_CODES"] = "RD1"
    prov = get_provider(app)
    assert prov.__class__.__name__ == "CubeMetricsProvider"


def test_get_provider_cube_requires_scope_codes(app):
    app.config["USE_MOCK_DATA"] = False
    app.config["CUBE_API_URL"] = "https://cube.example"
    app.config["CUBE_API_TOKEN"] = "tok"
    app.config["CUBE_REDISPATCH_CODES"] = ""
    app.config["CUBE_RESTRICTION_TYPE_CODES"] = ""
    with pytest.raises(ConfigurationError, match="WASTED_SUN_CUBE"):
        get_provider(app)
