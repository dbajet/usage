from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class SensorSample(NamedTuple):
    entity_id: str
    name: str
    unit: str
    value: float
    # When the value last changed, which is what a sample is keyed by: a reading
    # re-sent unchanged ten minutes later is the same sample, not a new one.
    measured_at: datetime
    battery: int | None = None
    # When Home Assistant last heard this value confirmed, which is a different
    # fact and belongs to the thermometer rather than to the reading. A room
    # holding 19.4 all afternoon has an afternoon-old `measured_at` and a
    # minute-old `reported_at`; a thermometer whose battery died has neither
    # moving. Absent from a push that predates the field, and then unknown
    # rather than assumed.
    reported_at: datetime | None = None

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "unit": self.unit,
            "value": self.value,
            "measured_at": self.measured_at.isoformat(),
            "battery": self.battery,
            "reported_at": None if self.reported_at is None else self.reported_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorSample:
        reported_at = data.get("reported_at")
        return cls(
            entity_id=str(data.get("entity_id") or ""),
            name=str(data.get("name") or ""),
            unit=str(data.get("unit") or ""),
            value=float(data.get("value") or 0.0),
            measured_at=datetime.fromisoformat(str(data.get("measured_at") or "1970-01-01T00:00:00+00:00")),
            battery=None if data.get("battery") is None else int(data["battery"]),
            reported_at=None if reported_at is None else datetime.fromisoformat(str(reported_at)),
        )
