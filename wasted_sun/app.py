import os

from dotenv import load_dotenv
from flask import Flask, session
from flask_babel import Babel, get_locale as babel_get_locale

from wasted_sun.config import get_config
from wasted_sun.views import bp as main_bp


def create_app() -> Flask:
    load_dotenv()
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    cfg = get_config()
    app.config.from_object(cfg)

    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(_root, "translations")

    if not app.config.get("DATABASE_URL"):
        app.config["USE_MOCK_DATA"] = True

    app.config.setdefault(
        "HOUSEHOLD_DAY_KWH",
        os.environ.get("HOUSEHOLD_DAY_KWH", "12"),
    )

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
    return app
