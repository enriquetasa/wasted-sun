from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from wasted_sun.models import DailyMetrics
from wasted_sun.views import _show_eur


def test_index_redirects_to_today(client):
    r = client.get("/")
    assert r.status_code == 302
    madrid_today = datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
    assert madrid_today in r.headers["Location"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.data == b"ok"


def test_day_page_spanish_default(client):
    d = date(2024, 6, 15)
    r = client.get(f"/{d.isoformat()}/")
    assert r.status_code == 200
    assert b"lang=\"es\"" in r.data
    assert (
        b"sol desperdiciada" in r.data.lower()
        or b"pen\xednsula" in r.data
        or b"peninsul" in r.data.lower()
    )


def test_day_page_english_after_session(client):
    d = date(2024, 6, 15)
    with client.session_transaction() as sess:
        sess["locale"] = "en"
    r = client.get(f"/{d.isoformat()}/")
    assert r.status_code == 200
    assert b"Wasted Sun" in r.data


def test_future_date_404(client):
    far = date.today() + timedelta(days=400)
    r = client.get(f"/{far.isoformat()}/")
    assert r.status_code == 404


def test_set_locale_redirect(client):
    r = client.get("/set-locale/en/?next=/2024-06-15/", follow_redirects=False)
    assert r.status_code == 302
    assert "/2024-06-15/" in r.headers["Location"]


def test_set_locale_rejects_open_redirect(client):
    for payload in (
        "https://evil.example/",
        "//evil.example/",
        "\\evil.example/",
        "javascript:alert(1)",
    ):
        r = client.get(f"/set-locale/en/?next={payload}", follow_redirects=False)
        assert r.status_code == 302
        assert "evil" not in r.headers["Location"]
        assert "javascript" not in r.headers["Location"]


def test_invalid_date_string_404(client):
    r = client.get("/not-a-date/")
    assert r.status_code == 404


def test_date_before_earliest_404(client):
    r = client.get("/2020-01-01/")
    assert r.status_code == 404


def test_error_page_has_back_link(client):
    r = client.get("/not-a-date/")
    assert r.status_code == 404
    assert b"Back to today" in r.data or b"Volver a hoy" in r.data


def test_lang_query_param_switches_locale(client):
    d = date(2024, 6, 15)
    r = client.get(f"/{d.isoformat()}/?lang=en")
    assert r.status_code == 200
    assert b"Wasted Sun" in r.data

    r = client.get(f"/{d.isoformat()}/?lang=es")
    assert r.status_code == 200
    assert b"sol desperdiciada" in r.data.lower()


def test_show_eur_when_cube_prices_without_flat_rate(app):
    app.config["EUR_PER_MWH"] = None
    metrics = DailyMetrics(
        day=date(2024, 6, 15),
        hourly=(),
        day_total_mwh=Decimal("1"),
        day_total_eur=Decimal("50"),
        ytd_mwh=Decimal("1"),
        ytd_eur=Decimal("50"),
        mean_hourly_mwh=Decimal("0"),
        mean_hourly_eur=Decimal("0"),
        as_of=datetime.now(ZoneInfo("Europe/Madrid")),
        earliest_available_date=date(2024, 1, 1),
    )
    with app.app_context():
        assert _show_eur(metrics) is True


def test_set_locale_invalid_lang_redirects(client):
    r = client.get("/set-locale/fr/", follow_redirects=False)
    assert r.status_code == 302
