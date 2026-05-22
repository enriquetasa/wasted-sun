from datetime import date
from decimal import Decimal

from wasted_sun.data.cube_scope import D_MWH, D_PERIOD, D_PRICE_ESP
from wasted_sun.sync.materialize import day_row_from_cube_rows


def test_day_row_from_cube_rows_merges_periods():
    day = date(2024, 6, 15)
    rows = [
        {D_PERIOD: 1, D_MWH: 1, D_PRICE_ESP: 10},
        {D_PERIOD: 1, D_MWH: 2, D_PRICE_ESP: 10},
        {D_PERIOD: 2, D_MWH: 0.5, D_PRICE_ESP: 20},
    ]
    wide = day_row_from_cube_rows(day, rows, n_slots=2)
    assert wide is not None
    assert wide["date_day"] == day
    assert wide["qh_1_mwh"] == Decimal("3")
    assert wide["qh_2_mwh"] == Decimal("0.5")
    assert wide["total_mwh"] == Decimal("3.5")


def test_day_row_from_cube_rows_empty_returns_none():
    assert day_row_from_cube_rows(date(2024, 1, 1), [], n_slots=4) is None


def test_day_row_from_cube_rows_all_zero_returns_none():
    rows = [{D_PERIOD: 1, D_MWH: 0, D_PRICE_ESP: 0}]
    assert day_row_from_cube_rows(date(2024, 1, 1), rows, n_slots=2) is None
