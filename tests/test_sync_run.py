import os
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from wasted_sun.data.cube_scope import D_DATE, D_MWH, D_PERIOD
from wasted_sun.sync.run import build_parser, main


def test_build_parser_defaults():
    args = build_parser().parse_args([])
    assert args.days == 7
    assert args.dry_run is False
    assert args.full is False


def test_main_dry_run_skips_postgres(monkeypatch):
    monkeypatch.setenv("CUBE_API_URL", "https://cube.example")
    monkeypatch.setenv("CUBE_API_TOKEN", "secret")
    monkeypatch.setenv("WASTED_SUN_CUBE_REDISPATCH_CODES", "RD1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("WASTED_SUN_SYNC_DATABASE_URL", raising=False)

    loader = MagicMock()
    loader.fetch_earliest_latest.return_value = (date(2024, 6, 14), date(2024, 6, 15))
    loader.load_day_rows.side_effect = [
        [{D_PERIOD: 1, D_MWH: 1}],
        [],
    ]

    with patch("wasted_sun.sync.run.CubeSyncLoader", return_value=loader):
        code = main(["--days", "2", "--dry-run"])

    assert code == 0
    assert loader.load_day_rows.call_count == 2


def test_main_missing_cube_credentials(monkeypatch):
    monkeypatch.delenv("CUBE_API_URL", raising=False)
    monkeypatch.delenv("CUBE_API_TOKEN", raising=False)
    assert main([]) == 1


def test_main_from_requires_to(monkeypatch):
    monkeypatch.setenv("CUBE_API_URL", "https://cube.example")
    monkeypatch.setenv("CUBE_API_TOKEN", "secret")
    monkeypatch.setenv("WASTED_SUN_CUBE_REDISPATCH_CODES", "RD1")
    assert main(["--from", "2024-06-01"]) == 2


def test_cube_scope_or_filter():
    from wasted_sun.data.cube_scope import D_REDISPATCH, D_RESTRICTION, wasted_sun_filters

    f = wasted_sun_filters(("RD1",), ("RT9",))
    assert len(f) == 1
    assert "or" in f[0]
    assert f[0]["or"][0]["member"] == D_REDISPATCH
    assert f[0]["or"][1]["member"] == D_RESTRICTION


def test_cube_scope_single_list():
    from wasted_sun.data.cube_scope import wasted_sun_filters

    f = wasted_sun_filters(("RD1",), ())
    assert len(f) == 1
    assert f[0]["operator"] == "equals"
