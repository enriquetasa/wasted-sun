from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote, urlencode

from flask import (
    Blueprint,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _

from wasted_sun.data.base import get_provider
from wasted_sun.exceptions import ConfigurationError
from wasted_sun.formatting import fmt_decimal, fmt_eur, fmt_int, fmt_mwh
from wasted_sun.models import DayNotFoundError

bp = Blueprint("main", __name__)


def _today() -> date:
    return datetime.now(current_app.config["TIMEZONE"]).date()


def _provider():
    if "_metrics_provider" not in current_app.extensions:
        current_app.extensions["_metrics_provider"] = get_provider(current_app)
    return current_app.extensions["_metrics_provider"]


def _household_day_kwh() -> Decimal:
    return Decimal(current_app.config.get("HOUSEHOLD_DAY_KWH", "12"))


def _city_analogy_households(day_mwh: Decimal) -> int:
    if _household_day_kwh() <= 0:
        return 0
    equiv = (day_mwh * Decimal("1000")) / _household_day_kwh()
    return int(equiv.to_integral_value())


def _show_eur() -> bool:
    rate = current_app.config.get("EUR_PER_MWH")
    return rate is not None and rate > 0


@bp.before_app_request
def _locale_from_query() -> None:
    lang = request.args.get("lang")
    if lang in ("es", "en"):
        session["locale"] = lang


@bp.app_context_processor
def _inject_config() -> dict:
    return {
        "base_url": current_app.config["BASE_URL"],
        "plausible_domain": current_app.config.get("PLAUSIBLE_DOMAIN") or "",
        "plausible_script_url": current_app.config.get("PLAUSIBLE_SCRIPT_URL")
        or "https://plausible.io/js/script.js",
    }


@bp.route("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")


@bp.route("/")
def index():
    return redirect(url_for("main.day_view", day_str=_today().isoformat()), code=302)


@bp.route("/<day_str>/")
def day_view(day_str: str):
    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        return render_template("error.html", message=_("Invalid date.")), 404

    today = _today()
    if day > today:
        return render_template("error.html", message=_("No data for future dates.")), 404

    try:
        prov = _provider()
    except ConfigurationError:
        return render_template(
            "error.html",
            message=_("Invalid database configuration. Check environment variables."),
        ), 503

    try:
        earliest = prov.earliest_date()
    except RuntimeError:
        return render_template("error.html", message=_("No energy data loaded yet.")), 503
    if day < earliest:
        return render_template("error.html", message=_("No data before coverage starts.")), 404

    try:
        metrics = prov.get_daily_metrics(day)
    except DayNotFoundError:
        return render_template("error.html", message=_("No data for this date.")), 404

    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)
    prev_ok = prev_day >= earliest
    next_ok = next_day <= today

    share_path = f"{day.isoformat()}/"
    share_url = f"{current_app.config['BASE_URL'].rstrip('/')}/{share_path}"

    show_eur = _show_eur()
    if show_eur:
        share_text = _(
            "Spain (peninsula) wastes %(eur_h)s per hour on average in unused solar "
            "electricity on %(day)s — %(ytd)s so far this year. %(url)s"
        ) % {
            "eur_h": fmt_eur(metrics.mean_hourly_eur),
            "day": day.isoformat(),
            "ytd": fmt_eur(metrics.ytd_eur),
            "url": share_url,
        }
    else:
        share_text = _(
            "Spain (peninsula) wastes %(mwh_h)s per hour on average in unused solar "
            "electricity (MWh) on %(day)s — %(ytd)s MWh so far this year. %(url)s"
        ) % {
            "mwh_h": fmt_mwh(metrics.mean_hourly_mwh),
            "day": day.isoformat(),
            "ytd": fmt_mwh(metrics.ytd_mwh),
            "url": share_url,
        }

    linkedin = "https://www.linkedin.com/shareArticle?" + urlencode(
        {"url": share_url, "text": share_text}, quote_via=quote
    )
    bluesky = "https://bsky.app/intent/compose?" + urlencode({"text": share_text}, quote_via=quote)
    x_url = "https://x.com/intent/post?" + urlencode({"text": share_text}, quote_via=quote)

    chart_labels = [h.bucket_start.strftime("%H:%M") for h in metrics.hourly]
    chart_mwh = [float(h.mwh_unused) for h in metrics.hourly]

    homes = _city_analogy_households(metrics.day_total_mwh)

    return render_template(
        "day.html",
        metrics=metrics,
        day=day,
        today=today,
        earliest=earliest,
        prev_day=prev_day,
        next_day=next_day,
        prev_ok=prev_ok,
        next_ok=next_ok,
        fmt_mwh=fmt_mwh,
        fmt_eur=fmt_eur,
        fmt_decimal=fmt_decimal,
        fmt_int=fmt_int,
        share_linkedin=linkedin,
        share_bluesky=bluesky,
        share_x=x_url,
        chart_labels_json=json.dumps(chart_labels),
        chart_mwh_json=json.dumps(chart_mwh),
        city_homes_equiv=homes,
        household_day_kwh=_household_day_kwh(),
        show_eur=show_eur,
    )


@bp.route("/set-locale/<lang>/")
def set_locale(lang: str):
    if lang not in ("es", "en"):
        return redirect(url_for("main.index"))
    session["locale"] = lang
    dest = request.args.get("next") or "/"
    if not dest.startswith("/") or dest.startswith("//"):
        dest = url_for("main.index")
    return redirect(dest)
