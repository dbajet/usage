from __future__ import annotations

from typing import Any, NamedTuple


class SensorBreach(NamedTuple):
    """One sensor that just crossed one of its thresholds: what the alert email reports."""

    sensor_id: int
    name: str
    value: float
    unit: str
    state: str
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "state": self.state,
            "threshold": self.threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorBreach:
        return cls(
            sensor_id=int(data.get("sensor_id") or 0),
            name=str(data.get("name") or ""),
            value=float(data.get("value") or 0.0),
            unit=str(data.get("unit") or ""),
            state=str(data.get("state") or ""),
            threshold=float(data.get("threshold") or 0.0),
        )
