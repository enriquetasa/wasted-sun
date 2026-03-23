from datetime import date, timedelta


def test_index_redirects_to_today(client):
    r = client.get("/")
    assert r.status_code == 302
    assert date.today().isoformat() in r.headers["Location"]


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
        b"Sol desperdiciado" in r.data
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
    r = client.get("/set-locale/en/?next=https://evil.example/", follow_redirects=False)
    assert r.status_code == 302
    assert "evil" not in r.headers["Location"]
