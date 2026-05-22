from __future__ import annotations

import json
import time
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
    current_app.logger.info("fetching latest_available_date from provider")
    return _provider().latest_available_date()


def _provider():
    if "_metrics_provider" not in current_app.extensions:
        t0 = time.perf_counter()
        prov = get_provider(current_app)
        current_app.extensions["_metrics_provider"] = prov
        current_app.logger.info(
            "metrics provider initialized: %s (%dms)",
            prov.__class__.__name__,
            int((time.perf_counter() - t0) * 1000),
        )
    return current_app.extensions["_metrics_provider"]


def _household_day_kwh() -> Decimal:
    return Decimal(current_app.config.get("HOUSEHOLD_DAY_KWH", "12"))


def _city_analogy_households(day_mwh: Decimal) -> int:
    if _household_day_kwh() <= 0:
        return 0
    equiv = (day_mwh * Decimal("1000")) / _household_day_kwh()
    return int(equiv.to_integral_value())


def _using_cube() -> bool:
    prov = current_app.extensions.get("_metrics_provider")
    return prov is not None and prov.__class__.__name__ == "CubeMetricsProvider"


def _show_ytd() -> bool:
    if _using_cube() and current_app.config.get("CUBE_SKIP_YTD"):
        return False
    return True


def _share_page_url(day: date) -> str:
    base = (current_app.config.get("SHARE_SITE_URL") or "https://wasted.energy").rstrip("/")
    return f"{base}/{day.isoformat()}/"


def _build_share_text(
    day: date,
    metrics,
    *,
    show_eur: bool,
    show_ytd: bool,
    share_url: str,
) -> str:
    day_label = day.isoformat()
    if show_eur and show_ytd:
        return _(
            "On %(day)s, Spain left %(day_mwh)s of solar unused on the peninsula—about "
            "%(day_eur)s at market prices. So far this year: %(ytd)s. %(url)s"
        ) % {
            "day": day_label,
            "day_mwh": fmt_mwh(metrics.day_total_mwh),
            "day_eur": fmt_eur(metrics.day_total_eur),
            "ytd": fmt_eur(metrics.ytd_eur),
            "url": share_url,
        }
    if show_eur:
        return _(
            "On %(day)s, Spain left %(day_mwh)s of solar unused on the peninsula—about "
            "%(day_eur)s at market prices. %(url)s"
        ) % {
            "day": day_label,
            "day_mwh": fmt_mwh(metrics.day_total_mwh),
            "day_eur": fmt_eur(metrics.day_total_eur),
            "url": share_url,
        }
    if show_ytd:
        return _(
            "On %(day)s, the peninsula wasted %(day_mwh)s of solar power. Running total "
            "this year: %(ytd)s. %(url)s"
        ) % {
            "day": day_label,
            "day_mwh": fmt_mwh(metrics.day_total_mwh),
            "ytd": fmt_mwh(metrics.ytd_mwh),
            "url": share_url,
        }
    return _(
        "On %(day)s, Spain wasted %(day_mwh)s of solar on the peninsula. %(url)s"
    ) % {
        "day": day_label,
        "day_mwh": fmt_mwh(metrics.day_total_mwh),
        "url": share_url,
    }


def _show_eur(metrics=None) -> bool:
    rate = current_app.config.get("EUR_PER_MWH")
    if rate is not None and rate > 0:
        return True
    if metrics is not None and metrics.day_total_eur > 0:
        return True
    return False


@bp.before_app_request
def _before_request() -> None:
    current_app.logger.info(
        "request start %s %s endpoint=%s",
        request.method,
        request.path,
        request.endpoint,
    )
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
    current_app.logger.info("index handler start")
    t0 = time.perf_counter()
    try:
        latest = _latest_data_day()
    except ConfigurationError as e:
        current_app.logger.error(
            "index configuration error after %dms: %s",
            int((time.perf_counter() - t0) * 1000),
            e,
        )
        return render_template(
            "error.html",
            message=_("Invalid database configuration. Check environment variables."),
        ), 503
    except RuntimeError:
        return render_template("error.html", message=_("No energy data loaded yet.")), 503
    except Exception:
        current_app.logger.exception(
            "index failed to resolve latest data date after %dms",
            int((time.perf_counter() - t0) * 1000),
        )
        return render_template("error.html", message=_("Database temporarily unavailable.")), 503
    current_app.logger.info(
        "index redirect to latest day=%s provider=%s (%dms)",
        latest.isoformat(),
        _provider().__class__.__name__,
        int((time.perf_counter() - t0) * 1000),
    )
    return redirect(url_for("main.day_view", day_str=latest.isoformat()), code=302)


@bp.route("/<day_str>/")
def day_view(day_str: str):
    current_app.logger.info("day_view handler start day_str=%s", day_str)
    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        return render_template("error.html", message=_("Invalid date.")), 404

    try:
        prov = _provider()
    except ConfigurationError as e:
        current_app.logger.error("day_view configuration error: %s", e)
        return render_template(
            "error.html",
            message=_("Invalid database configuration. Check environment variables."),
        ), 503

    current_app.logger.info("day_view loading metrics for %s", day)
    t0 = time.perf_counter()
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
        current_app.logger.exception(
            "day_view failed day=%s provider=%s after %dms",
            day,
            prov.__class__.__name__,
            int((time.perf_counter() - t0) * 1000),
        )
        return render_template("error.html", message=_("Database temporarily unavailable.")), 503

    current_app.logger.info(
        "day_view ok day=%s provider=%s skip_ytd=%s (%dms)",
        day,
        prov.__class__.__name__,
        not _show_ytd(),
        int((time.perf_counter() - t0) * 1000),
    )

    earliest = metrics.earliest_available_date
    latest_day = metrics.latest_available_date

    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)
    prev_ok = prev_day >= earliest
    next_ok = next_day <= latest_day

    share_url = _share_page_url(day)
    show_eur = _show_eur(metrics)
    show_ytd = _show_ytd()
    share_text = _build_share_text(
        day, metrics, show_eur=show_eur, show_ytd=show_ytd, share_url=share_url
    )

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
        show_ytd=show_ytd,
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
