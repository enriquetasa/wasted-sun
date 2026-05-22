"""Shared WastedEnergy cube members and wasted-sun scope filters."""

from __future__ import annotations

from typing import Any

CUBE = "WastedEnergy"
D_DATE = f"{CUBE}.DateDay"
D_PERIOD = f"{CUBE}.QuarterPeriod"
D_MWH = f"{CUBE}.EnergyMwh"
D_PRICE_ESP = f"{CUBE}.PriceEspEurMwh"
D_REDISPATCH = f"{CUBE}.RedispatchCode"
D_RESTRICTION = f"{CUBE}.RestrictionTypeCode"


def wasted_sun_filters(
    redispatch_codes: tuple[str, ...],
    restriction_type_codes: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Row matches if RedispatchCode OR RestrictionTypeCode is in the allowlists."""
    clauses: list[dict[str, Any]] = []
    if redispatch_codes:
        clauses.append(
            {
                "member": D_REDISPATCH,
                "operator": "equals",
                "values": list(redispatch_codes),
            }
        )
    if restriction_type_codes:
        clauses.append(
            {
                "member": D_RESTRICTION,
                "operator": "equals",
                "values": list(restriction_type_codes),
            }
        )
    if len(clauses) == 1:
        return clauses
    return [{"or": clauses}]
