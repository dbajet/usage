from __future__ import annotations

from typing import Any, NamedTuple


class WaterMeter(NamedTuple):
    """A meter as the EyeOnWater account lists it.

    The portal shows a nineteen-digit `uuid` and a nine-digit `meter_id` side by
    side, and only the first one works in an export; the second answers with a
    crash rather than an explanation. So the app asks the account instead of
    asking a person to copy the right one.
    """

    uuid: str
    meter_id: str = ""
    timezone: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"uuid": self.uuid, "meter_id": self.meter_id, "timezone": self.timezone}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaterMeter:
        return cls(
            uuid=str(data.get("uuid") or ""),
            meter_id=str(data.get("meter_id") or ""),
            timezone=str(data.get("timezone") or ""),
        )
