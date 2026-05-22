from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import session

from wasted_sun.models import DailyMetrics, HourlyPoint
from wasted_sun.views import _build_share_text, _share_page_url


def test_share_page_url_uses_canonical_site(app):
    with app.app_context():
        app.config["SHARE_SITE_URL"] = "https://wasted.energy"
        assert _share_page_url(date(2024, 6, 15)) == "https://wasted.energy/2024-06-15/"


def test_build_share_text_natural_tone(app):
    tz = ZoneInfo("Europe/Madrid")
    day = date(2024, 6, 15)
    metrics = DailyMetrics(
        day=day,
        hourly=(
            HourlyPoint(
                bucket_start=__import__("datetime").datetime(2024, 6, 15, 12, tzinfo=tz),
                mwh_unused=Decimal("1"),
                eur_waste=Decimal("50"),
            ),
        ),
        day_total_mwh=Decimal("10"),
        day_total_eur=Decimal("500"),
        ytd_mwh=Decimal("100"),
        ytd_eur=Decimal("5000"),
        mean_hourly_mwh=Decimal("1"),
        mean_hourly_eur=Decimal("50"),
        as_of=__import__("datetime").datetime(2024, 6, 15, 23, tzinfo=tz),
        earliest_available_date=date(2024, 1, 1),
        latest_available_date=day,
    )
    url = "https://wasted.energy/2024-06-15/"
    with app.test_request_context():
        text = _build_share_text(
            day, metrics, show_eur=True, show_ytd=True, share_url=url
        )
    assert "2024-06-15" in text
    assert url in text
    assert "OMIE" not in text
    assert "/h" not in text
    with app.test_request_context("/"):
        session["locale"] = "en"
        en = _build_share_text(
            day, metrics, show_eur=True, show_ytd=True, share_url=url
        )
    assert "left" in en and "Spain" in en
