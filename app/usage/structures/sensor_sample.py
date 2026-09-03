from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class SensorSample(NamedTuple):
    entity_id: str
    name: str
    unit: str
    value: float
    measured_at: datetime

    def to_dict(self) -> dict[str, str | float]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "unit": self.unit,
            "value": self.value,
            "measured_at": self.measured_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorSample:
        return cls(
            entity_id=str(data.get("entity_id") or ""),
            name=str(data.get("name") or ""),
            unit=str(data.get("unit") or ""),
            value=float(data.get("value") or 0.0),
            measured_at=datetime.fromisoformat(str(data.get("measured_at") or "1970-01-01T00:00:00+00:00")),
        )
