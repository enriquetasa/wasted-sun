"""Signed source values vs positive headline waste for KPIs and YTD."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence


def net_mwh_from_qh(qh: Sequence[Decimal], n_slots: int) -> Decimal:
    """Algebraic sum of quarter-hour slots (signed in upstream data)."""
    return sum(qh[:n_slots], start=Decimal("0"))


def headline_waste_mwh(net_mwh: Decimal) -> Decimal:
    """Positive magnitude shown as 'wasted' in KPIs, share text, and YTD."""
    return abs(net_mwh)


def headline_waste_eur(net_mwh: Decimal, eur_per_mwh: Decimal | None) -> Decimal:
    rate = eur_per_mwh if eur_per_mwh is not None else Decimal("0")
    if rate <= 0:
        return Decimal("0")
    return (headline_waste_mwh(net_mwh) * rate).quantize(Decimal("0.01"))


def mean_hourly_waste_from_headline(
    headline_mwh: Decimal,
    headline_eur: Decimal,
    n_hours: int,
) -> tuple[Decimal, Decimal]:
    """Average 'per hour' subtitle aligned with headline totals (not signed bar mean)."""
    if n_hours <= 0:
        return Decimal("0"), Decimal("0")
    n = Decimal(n_hours)
    return headline_mwh / n, headline_eur / n
