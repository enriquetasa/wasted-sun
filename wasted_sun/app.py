import logging
import os
import sys
from decimal import Decimal

from dotenv import load_dotenv
from flask import Flask, session
from flask_babel import Babel, get_locale as babel_get_locale

from wasted_sun.config import get_config
from wasted_sun.exceptions import ConfigurationError
from wasted_sun.sql_guard import validate_plausible_domain, validate_plausible_script_url
from wasted_sun.views import bp as main_bp


def _configure_logging(app: Flask) -> None:
    """Emit INFO+ logs to stdout for container/App Platform log drains."""
    level = logging.DEBUG if app.debug else logging.INFO
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            stream=sys.stdout,
        )
    root.setLevel(level)
    app.logger.setLevel(level)


def create_app() -> Flask:
    load_dotenv()
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    cfg = get_config()
    app.config.from_object(cfg)
    _configure_logging(app)

    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(_root, "translations")

    if not app.config.get("DATABASE_URL") and not app.config.get("CUBE_API_URL"):
        app.config["USE_MOCK_DATA"] = True

    raw_eur = os.environ.get("WASTED_SUN_EUR_PER_MWH")
    if raw_eur is not None and str(raw_eur).strip() != "":
        app.config["EUR_PER_MWH"] = Decimal(str(raw_eur).strip())
    else:
        app.config["EUR_PER_MWH"] = None

    mockish = (
        app.config.get("USE_MOCK_DATA")
        or (not app.config.get("DATABASE_URL") and not app.config.get("CUBE_API_URL"))
    )
    if mockish and app.config["EUR_PER_MWH"] is None:
        app.config["EUR_PER_MWH"] = Decimal("52")

    app.config.setdefault(
        "HOUSEHOLD_DAY_KWH",
        os.environ.get("HOUSEHOLD_DAY_KWH", "12"),
    )

    try:
        pd = validate_plausible_domain(app.config.get("PLAUSIBLE_DOMAIN") or "")
        app.config["PLAUSIBLE_DOMAIN"] = pd
        ps = validate_plausible_script_url(app.config.get("PLAUSIBLE_SCRIPT_URL") or "")
        if ps:
            app.config["PLAUSIBLE_SCRIPT_URL"] = ps
    except ValueError as e:
        raise ConfigurationError(f"Invalid analytics configuration: {e}") from e

    babel = Babel()

    def select_locale() -> str:
        # Explicit picker only; first-time visitors always get Spanish per product spec.
        loc = session.get("locale")
        if loc in ("es", "en"):
            return loc
        return app.config["BABEL_DEFAULT_LOCALE"]

    babel.init_app(app, locale_selector=select_locale)
    app.jinja_env.globals["get_locale"] = babel_get_locale

    app.register_blueprint(main_bp)
    cube_url_set = bool((app.config.get("CUBE_API_URL") or "").strip())
    cube_token_set = bool((app.config.get("CUBE_API_TOKEN") or "").strip())
    cube_redispatch_set = bool((app.config.get("CUBE_REDISPATCH_CODES") or "").strip())
    cube_restriction_set = bool(
        (app.config.get("CUBE_RESTRICTION_TYPE_CODES") or "").strip()
    )
    app.logger.info(
        "wasted_sun startup mock=%s postgres=%s cube_url_set=%s cube_token_set=%s "
        "cube_redispatch_set=%s cube_restriction_set=%s data_source=%r cube_skip_ytd=%s",
        bool(app.config.get("USE_MOCK_DATA")),
        bool(app.config.get("DATABASE_URL")),
        cube_url_set,
        cube_token_set,
        cube_redispatch_set,
        cube_restriction_set,
        app.config.get("DATA_SOURCE") or "",
        app.config.get("CUBE_SKIP_YTD"),
    )
    using_cube = (
        not app.config.get("USE_MOCK_DATA")
        and (
            (app.config.get("DATA_SOURCE") or "").strip().lower() == "cube"
            or (cube_url_set and not app.config.get("DATABASE_URL"))
        )
    )
    if using_cube:
        if not cube_token_set:
            app.logger.error("cube config incomplete: CUBE_API_TOKEN is missing or empty")
        if not cube_redispatch_set and not cube_restriction_set:
            app.logger.error(
                "cube config incomplete: set WASTED_SUN_CUBE_REDISPATCH_CODES "
                "and/or WASTED_SUN_CUBE_RESTRICTION_TYPE_CODES"
            )
    return app
