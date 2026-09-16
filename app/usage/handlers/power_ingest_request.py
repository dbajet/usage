from __future__ import annotations

from pydantic import BaseModel


class PowerIngestRequest(BaseModel):
    # What the gateway reports this instant: the tiles' whole job.
    production_power: float | None = None
    consumption_power: float | None = None
    battery_level: float | None = None
    # Lifetime counters; the app differences consecutive pushes rather than
    # trusting a rate, so a missed push costs nothing.
    production_lifetime: float | None = None
    consumption_lifetime: float | None = None
    # The unit each number is in, as Home Assistant names it. An Envoy reports
    # kW and MWh, and a display unit can be overridden from the interface, so
    # the reading says what it means rather than the sender doing the sum.
    # Empty means the base unit, which is what the field name implies.
    production_power_unit: str = ""
    consumption_power_unit: str = ""
    production_lifetime_unit: str = ""
    consumption_lifetime_unit: str = ""
    # Empty means "now": Home Assistant sends the gateway's own instant when it has one.
    measured_at: str = ""
