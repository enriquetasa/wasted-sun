from decimal import Decimal

from wasted_sun.waste_display import (
    headline_waste_eur,
    headline_waste_mwh,
    mean_hourly_waste_from_headline,
    net_mwh_from_qh,
)


def test_headline_waste_mwh_is_absolute_net():
    assert headline_waste_mwh(Decimal("-11086.624")) == Decimal("11086.624")
    assert headline_waste_mwh(Decimal("5")) == Decimal("5")


def test_headline_waste_eur_uses_magnitude():
    assert headline_waste_eur(Decimal("-10"), Decimal("50")) == Decimal("500.00")


def test_net_mwh_from_qh():
    qh = [Decimal("-1"), Decimal("-2"), Decimal("1")]
    assert net_mwh_from_qh(qh, 3) == Decimal("-2")


def test_mean_hourly_waste_from_headline():
    mwh, eur = mean_hourly_waste_from_headline(Decimal("24"), Decimal("120"), 24)
    assert mwh == Decimal("1")
    assert eur == Decimal("5")
