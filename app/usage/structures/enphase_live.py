from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class EnphaseLive(NamedTuple):
    """What the gateway is doing right now, as Home Assistant last saw it.

    Power, not energy: a live page answers "what are the panels making this
    second", and integrating watts to answer that would only make it less true.
    The lifetime counters travel with it because they are what the intervals in
    `enphase_points` are differenced from - the reading is the fact, and the
    interval is derived from two of them, exactly as a meter reading is.
    """

    house_id: int
    measured_at: datetime
    production_power: float | None = None
    consumption_power: float | None = None
    battery_level: float | None = None
    production_lifetime: float | None = None
    consumption_lifetime: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "house_id": self.house_id,
            "measured_at": self.measured_at.isoformat(),
            "production_power": self.production_power,
            "consumption_power": self.consumption_power,
            "battery_level": self.battery_level,
            "production_lifetime": self.production_lifetime,
            "consumption_lifetime": self.consumption_lifetime,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnphaseLive:
        return cls(
            house_id=int(data.get("house_id") or 0),
            measured_at=datetime.fromisoformat(str(data.get("measured_at") or "1970-01-01T00:00:00+00:00")),
            production_power=None if data.get("production_power") is None else float(data["production_power"]),
            consumption_power=None if data.get("consumption_power") is None else float(data["consumption_power"]),
            battery_level=None if data.get("battery_level") is None else float(data["battery_level"]),
            production_lifetime=None if data.get("production_lifetime") is None else float(data["production_lifetime"]),
            consumption_lifetime=None if data.get("consumption_lifetime") is None else float(data["consumption_lifetime"]),
        )
