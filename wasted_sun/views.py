from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote, urlencode, urlparse

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
from wasted_sun.formatting import fmt_eur, fmt_int, fmt_mwh
from wasted_sun.models import DayNotFoundError

bp = Blueprint("main", __name__)


def _latest_data_day() -> date:
    return _provider().latest_available_date()


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


def _show_eur(metrics=None) -> bool:
    rate = current_app.config.get("EUR_PER_MWH")
    if rate is not None and rate > 0:
        return True
    if metrics is not None and metrics.day_total_eur > 0:
        return True
    return False


@bp.before_app_request
def _locale_from_query() -> None:
    lang = request.args.get("lang")
    if lang in ("es", "en"):
        session["locale"] = lang


@bp.app_context_processor
def _inject_config() -> dict:
    return {
        "plausible_domain": current_app.config.get("PLAUSIBLE_DOMAIN") or "",
        "plausible_script_url": current_app.config.get("PLAUSIBLE_SCRIPT_URL")
        or "https://plausible.io/js/script.js",
    }


@bp.route("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")


@bp.route("/")
def index():
    try:
        latest = _latest_data_day()
    except ConfigurationError:
        return render_template(
            "error.html",
            message=_("Invalid database configuration. Check environment variables."),
        ), 503
    except RuntimeError:
        return render_template("error.html", message=_("No energy data loaded yet.")), 503
    except Exception:
        current_app.logger.exception("Failed to resolve latest data date")
        return render_template("error.html", message=_("Database temporarily unavailable.")), 503
    return redirect(url_for("main.day_view", day_str=latest.isoformat()), code=302)


@bp.route("/<day_str>/")
def day_view(day_str: str):
    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        return render_template("error.html", message=_("Invalid date.")), 404

    try:
        prov = _provider()
    except ConfigurationError:
        return render_template(
            "error.html",
            message=_("Invalid database configuration. Check environment variables."),
        ), 503

    try:
        latest_day = prov.latest_available_date()
    except RuntimeError:
        return render_template("error.html", message=_("No energy data loaded yet.")), 503
    except Exception:
        current_app.logger.exception("Failed to resolve latest data date")
        return render_template("error.html", message=_("Database temporarily unavailable.")), 503

    if day > latest_day:
        return render_template("error.html", message=_("No data for future dates.")), 404

    try:
        metrics = prov.get_daily_metrics(day)
    except DayNotFoundError:
        try:
            earliest = prov.earliest_date()
        except (RuntimeError, Exception):
            return render_template("error.html", message=_("No data for this date.")), 404
        if day < earliest:
            return render_template("error.html", message=_("No data before coverage starts.")), 404
        return render_template("error.html", message=_("No data for this date.")), 404
    except RuntimeError:
        return render_template("error.html", message=_("No energy data loaded yet.")), 503
    except Exception:
        current_app.logger.exception("Failed to load metrics for %s", day)
        return render_template("error.html", message=_("Database temporarily unavailable.")), 503

    earliest = metrics.earliest_available_date

    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)
    prev_ok = prev_day >= earliest
    next_ok = next_day <= latest_day

    share_path = f"{day.isoformat()}/"
    share_url = f"{current_app.config['BASE_URL'].rstrip('/')}/{share_path}"

    show_eur = _show_eur(metrics)
    if show_eur:
        share_text = _(
            "%(day)s — %(day_mwh)s unused solar (Spanish peninsula); illustrative ~%(day_eur)s "
            "(site €/MWh). ~%(eur_h)s/h avg. YTD: %(ytd)s. %(url)s"
        ) % {
            "day": day.isoformat(),
            "day_mwh": fmt_mwh(metrics.day_total_mwh),
            "day_eur": fmt_eur(metrics.day_total_eur),
            "eur_h": fmt_eur(metrics.mean_hourly_eur),
            "ytd": fmt_eur(metrics.ytd_eur),
            "url": share_url,
        }
    else:
        share_text = _(
            "%(day)s — %(day_mwh)s unused solar (Spanish peninsula). "
            "~%(mwh_h)s/h avg. YTD: %(ytd)s. %(url)s"
        ) % {
            "day": day.isoformat(),
            "day_mwh": fmt_mwh(metrics.day_total_mwh),
            "mwh_h": fmt_mwh(metrics.mean_hourly_mwh),
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
    zero = Decimal("0")
    zero_mwh = fmt_mwh(zero)
    zero_eur = fmt_eur(zero)

    return render_template(
        "day.html",
        metrics=metrics,
        day=day,
        latest_day=latest_day,
        prev_day=prev_day,
        next_day=next_day,
        prev_ok=prev_ok,
        next_ok=next_ok,
        fmt_mwh=fmt_mwh,
        fmt_eur=fmt_eur,
        fmt_int=fmt_int,
        share_linkedin=linkedin,
        share_bluesky=bluesky,
        share_x=x_url,
        chart_labels_json=json.dumps(chart_labels),
        chart_mwh_json=json.dumps(chart_mwh),
        city_homes_equiv=homes,
        household_day_kwh=_household_day_kwh(),
        show_eur=show_eur,
        zero_mwh=zero_mwh,
        zero_eur=zero_eur,
    )


@bp.route("/set-locale/<lang>/")
def set_locale(lang: str):
    if lang not in ("es", "en"):
        return redirect(url_for("main.index"))
    session["locale"] = lang
    dest = request.args.get("next") or "/"
    parsed = urlparse(dest)
    if parsed.scheme or parsed.netloc or not dest.startswith("/"):
        dest = url_for("main.index")
    return redirect(dest)
