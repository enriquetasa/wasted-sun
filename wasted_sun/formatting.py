from __future__ import annotations

from decimal import Decimal

from babel.numbers import format_currency, format_decimal
from flask_babel import get_locale


def fmt_decimal(value: Decimal, places: int = 2) -> str:
    loc = str(get_locale() or "es")
    pattern = f"#,##0.{'0' * places}"
    return format_decimal(value, format=pattern, locale=loc)


def fmt_mwh(value: Decimal) -> str:
    return f"{fmt_decimal(value, 3)} MWh"


def fmt_eur(value: Decimal) -> str:
    loc = str(get_locale() or "es")
    return format_currency(value, "EUR", locale=loc)


def fmt_int(value: int) -> str:
    loc = str(get_locale() or "es")
    return format_decimal(value, format="#,##0", locale=loc)
