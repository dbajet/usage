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
    # Whether a sensor this sample creates starts out of the graphs. A push
    # never sets it - the Home Assistant entity map is curated, and everything
    # in it was chosen. The SwitchBot pull does, for the humidity it collects
    # beside a temperature: it is the evidence that the thermometer is still
    # being heard from, not a curve anybody asked to see on that axis. It says
    # nothing about a sensor that already exists, which is the user's to show
    # or hide as they please.
    hidden: bool = False

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "unit": self.unit,
            "value": self.value,
            "measured_at": self.measured_at.isoformat(),
            "battery": self.battery,
            "reported_at": None if self.reported_at is None else self.reported_at.isoformat(),
            "hidden": self.hidden,
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
            hidden=bool(data.get("hidden")),
        )
