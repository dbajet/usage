from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class SensorState(NamedTuple):
    """What a sensor already holds, so a pull can tell a change from a repeat.

    A pushed sample arrives with the instant its value changed already worked
    out; a pulled one does not, and the only way to date it is against what is
    already stored. Hence the last value and its instant, and the charge, which
    belongs to the sensor rather than to any one reading.
    """

    entity_hash: str
    value: float | None = None
    measured_at: datetime | None = None
    battery: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_hash": self.entity_hash,
            "value": self.value,
            "measured_at": None if self.measured_at is None else self.measured_at.isoformat(),
            "battery": self.battery,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorState:
        measured_at = data.get("measured_at")
        return cls(
            entity_hash=str(data.get("entity_hash") or ""),
            value=None if data.get("value") is None else float(data["value"]),
            measured_at=None if measured_at is None else datetime.fromisoformat(str(measured_at)),
            battery=None if data.get("battery") is None else int(data["battery"]),
        )
