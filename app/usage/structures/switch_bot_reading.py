from __future__ import annotations

from typing import Any, NamedTuple


class SwitchBotReading(NamedTuple):
    """What one SwitchBot thermometer reads this second, and nothing about when.

    The cloud answers "it is 19.4" and never "it became 19.4 at 14:02", so
    there is no instant here to carry: whoever stores this works out both the
    instant the value changed and the instant the device was last heard from,
    by comparing this reading with the one before it.

    The humidity is part of that comparison rather than decoration: it moves
    while a room's temperature holds still, which is exactly when telling a
    live thermometer from a dead one gets hard.
    """

    device_id: str
    temperature: float
    humidity: float | None = None
    battery: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "battery": self.battery,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwitchBotReading:
        return cls(
            device_id=str(data.get("device_id") or ""),
            temperature=float(data.get("temperature") or 0.0),
            humidity=None if data.get("humidity") is None else float(data["humidity"]),
            battery=None if data.get("battery") is None else int(data["battery"]),
        )
