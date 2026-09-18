from __future__ import annotations

from typing import Any, NamedTuple


class SwitchBotHub(NamedTuple):
    """One place an account's devices stand in, as the picker offers it.

    `devices` is what makes a hub recognisable as this house's - "Grenier,
    Dehors, Freezer" says more than any identifier - and it leaves out the hub
    itself, which is already the line's name. A group with no name is the one
    for devices the cloud cannot place at all.
    """

    hub_id: str
    name: str = ""
    devices: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"hub_id": self.hub_id, "name": self.name, "devices": list(self.devices)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwitchBotHub:
        return cls(
            hub_id=str(data.get("hub_id") or ""),
            name=str(data.get("name") or ""),
            devices=tuple(str(device) for device in data.get("devices") or ()),
        )
