from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class SwitchBotEvent(NamedTuple):
    """One `changeReport` SwitchBot posted, as the app reads it.

    The whole reason the webhook exists: `measured_at` is the instant the device
    sampled the reading, which neither of the other two ways in can supply. A
    pushed sample gets it from Home Assistant's own clock, and a polled one has
    to be dated against the reading before it, to somewhere inside the interval.

    The temperature is in Celsius by the time it arrives here, whatever scale
    the event named, since that is the unit everything else is stored in.
    """

    device_id: str
    temperature: float
    measured_at: datetime
    humidity: float | None = None
    battery: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "temperature": self.temperature,
            "measured_at": self.measured_at.isoformat(),
            "humidity": self.humidity,
            "battery": self.battery,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwitchBotEvent:
        return cls(
            device_id=str(data.get("device_id") or ""),
            temperature=float(data.get("temperature") or 0.0),
            measured_at=datetime.fromisoformat(str(data.get("measured_at") or "1970-01-01T00:00:00+00:00")),
            humidity=None if data.get("humidity") is None else float(data["humidity"]),
            battery=None if data.get("battery") is None else int(data["battery"]),
        )
