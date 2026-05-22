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

    # cube | postgres | mock (empty: cube if CUBE_API_URL set, else postgres/mock)
    DATA_SOURCE = os.environ.get("WASTED_SUN_DATA_SOURCE", "").strip().lower()
    CUBE_API_URL = os.environ.get("CUBE_API_URL", "").strip()
    CUBE_API_TOKEN = os.environ.get("CUBE_API_TOKEN", "").strip()
    # Comma-separated allowlists — only these rows count as wasted sun (required for Cube mode).
    CUBE_REDISPATCH_CODES = os.environ.get("WASTED_SUN_CUBE_REDISPATCH_CODES", "").strip()
    CUBE_RESTRICTION_TYPE_CODES = os.environ.get(
        "WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES", ""
    ).strip()
    CUBE_HTTP_TIMEOUT_SEC = int(os.environ.get("WASTED_SUN_CUBE_HTTP_TIMEOUT_SEC", "90"))
    # YTD loads the full year from Cube row-by-row; skip until Cube is fast enough.
    CUBE_SKIP_YTD = _bool("WASTED_SUN_CUBE_SKIP_YTD", default=True)
    CUBE_YTD_TIMEOUT_SEC = int(os.environ.get("WASTED_SUN_CUBE_YTD_TIMEOUT_SEC", "20"))

    # Plausible (optional)
    PLAUSIBLE_DOMAIN = os.environ.get("PLAUSIBLE_DOMAIN", "").strip()
    PLAUSIBLE_SCRIPT_URL = os.environ.get(
        "PLAUSIBLE_SCRIPT_URL", "https://plausible.io/js/script.js"
    ).strip()

    # Postgres: one or more rows per date_day, quarter-hourly qh_1_mwh … qh_N_mwh
    PG_TABLE = os.environ.get("WASTED_SUN_PG_TABLE", "wasted_sun_qh_daily")
    PG_COL_DATE_DAY = os.environ.get("WASTED_SUN_PG_COL_DATE_DAY", "date_day")
    PG_COL_TOTAL_MWH = os.environ.get("WASTED_SUN_PG_COL_TOTAL_MWH", "total_mwh")
    PG_COL_TOTAL_EUR = os.environ.get("WASTED_SUN_PG_COL_TOTAL_EUR", "total_eur")
    PG_QH_SLOTS = int(os.environ.get("WASTED_SUN_PG_QH_SLOTS", "100"))
    PG_AS_OF_QUERY = os.environ.get(
        "WASTED_SUN_PG_AS_OF_QUERY",
        "",
    ).strip()
    # Safer than raw SQL: MAX(column) from table (each part validated; schema.table allowed).
    PG_AS_OF_META_TABLE = os.environ.get("WASTED_SUN_PG_AS_OF_META_TABLE", "").strip()
    PG_AS_OF_META_COLUMN = os.environ.get("WASTED_SUN_PG_AS_OF_META_COLUMN", "").strip()


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    USE_MOCK_DATA = _bool("USE_MOCK_DATA", default=False)
    # False for local docker over http:// — locale cookie will not persist over HTTPS-only flag
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", default=True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
