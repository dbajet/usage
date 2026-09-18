from __future__ import annotations

from typing import Any, NamedTuple


class SwitchBotDevice(NamedTuple):
    """A device as the SwitchBot account lists it.

    `hub_id` is the only thing the API says about where a device physically is:
    SwitchBot's own "Homes" never cross the API boundary, while every device
    names the hub that relays it - and a hub is a box in a room, which is the
    question a feed actually has to answer. A hub names itself here, so it
    stands for its own place rather than for nowhere.
    """

    device_id: str
    name: str = ""
    device_type: str = ""
    hub_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "device_type": self.device_type,
            "hub_id": self.hub_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwitchBotDevice:
        return cls(
            device_id=str(data.get("device_id") or ""),
            name=str(data.get("name") or ""),
            device_type=str(data.get("device_type") or ""),
            hub_id=str(data.get("hub_id") or ""),
        )
