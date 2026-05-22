from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from wasted_sun.timeseries import merge_qh_across_rows, hourly_mwh_from_qh, qh_series_to_hourly_points


def test_merge_qh_sums_rows():
    rows = [
        {"qh_1_mwh": 1, "qh_2_mwh": 2},
        {"qh_1_mwh": 0.5, "qh_2_mwh": 1},
    ]
    acc = merge_qh_across_rows(rows, n_slots=2)
    assert acc[0] == Decimal("1.5")
    assert acc[1] == Decimal("3")


def test_hourly_buckets_sum_four_qh():
    qh = [Decimal("1")] * 96 + [Decimal("10"), Decimal("0"), Decimal("0"), Decimal("0")]
    hours = hourly_mwh_from_qh(qh)
    assert len(hours) == 24
    assert hours[0] == Decimal("4")
    # Last hour uses qh_93–96 plus spill qh_97–100
    assert hours[23] == Decimal("4") + Decimal("10")


def test_qh_series_to_hourly_points_eur_rate():
    tz = ZoneInfo("Europe/Madrid")
    qh = [Decimal("2")] * 4 + [Decimal("0")] * 96
    hourly, dm, de = qh_series_to_hourly_points(date(2024, 1, 1), qh, tz, Decimal("10"))
    assert len(hourly) == 24
    assert dm == Decimal("8")
    assert de == Decimal("80")


def test_n_slots_truncates_tail_for_day_total():
    tz = ZoneInfo("Europe/Madrid")
    qh = [Decimal("1")] * 100
    _, dm96, _ = qh_series_to_hourly_points(
        date(2024, 1, 1), qh, tz, None, n_slots=96
    )
    assert dm96 == Decimal("96")
    _, dm100, _ = qh_series_to_hourly_points(
        date(2024, 1, 1), qh, tz, None, n_slots=100
    )
    assert dm100 == Decimal("100")


def test_merge_qh_case_insensitive_keys():
    rows = [{"QH_1_MWH": 2}]
    acc = merge_qh_across_rows(rows, n_slots=1)
    assert acc[0] == Decimal("2")


def test_qh_series_headline_uses_abs_net_for_negative_source():
    tz = ZoneInfo("Europe/Madrid")
    qh = [Decimal("-2")] * 4 + [Decimal("0")] * 96
    hourly, dm, de = qh_series_to_hourly_points(date(2024, 1, 1), qh, tz, Decimal("10"))
    assert hourly[0].mwh_unused == Decimal("-8")
    assert dm == Decimal("8")
    assert de == Decimal("80")
