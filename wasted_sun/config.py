import os
from zoneinfo import ZoneInfo


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    TIMEZONE = ZoneInfo(os.environ.get("APP_TIMEZONE", "Europe/Madrid"))
    BABEL_DEFAULT_LOCALE = "es"

    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")
    USE_MOCK_DATA = _bool("USE_MOCK_DATA", default=False)
    DATABASE_URL = os.environ.get("DATABASE_URL")

    # Plausible (optional)
    PLAUSIBLE_DOMAIN = os.environ.get("PLAUSIBLE_DOMAIN", "").strip()
    PLAUSIBLE_SCRIPT_URL = os.environ.get(
        "PLAUSIBLE_SCRIPT_URL", "https://plausible.io/js/script.js"
    ).strip()

    # Postgres hourly table (override when wiring real schema)
    PG_TABLE = os.environ.get("WASTED_SUN_PG_TABLE", "wasted_sun_hourly")
    PG_COL_TS = os.environ.get("WASTED_SUN_PG_COL_TS", "bucket_start")
    PG_COL_MWH = os.environ.get("WASTED_SUN_PG_COL_MWH", "mwh_unused")
    PG_COL_EUR = os.environ.get("WASTED_SUN_PG_COL_EUR", "eur_waste")
    PG_AS_OF_QUERY = os.environ.get(
        "WASTED_SUN_PG_AS_OF_QUERY",
        "",  # e.g. SELECT max(updated_at) FROM wasted_sun_meta
    )


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    USE_MOCK_DATA = _bool("USE_MOCK_DATA", default=False)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
