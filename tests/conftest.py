import os

import pytest

from wasted_sun.app import create_app

_CLEAN_ENV = {
    "DATABASE_URL": "",
    "USE_MOCK_DATA": "true",
    "FLASK_ENV": "development",
    "SECRET_KEY": "test-secret",
}


@pytest.fixture()
def app(monkeypatch):
    for key, val in _CLEAN_ENV.items():
        monkeypatch.setenv(key, val)
    for key in list(os.environ):
        if key.startswith("WASTED_SUN_") and key not in _CLEAN_ENV:
            monkeypatch.delenv(key, raising=False)
    app = create_app()
    app.config.update(TESTING=True)
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()
