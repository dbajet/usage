from __future__ import annotations

from usage.constants.constants import Constants
from usage.structures.switch_bot_device import SwitchBotDevice
from usage.structures.switch_bot_hub import SwitchBotHub


class SwitchBotHubs:
    """Which of an account's devices stand in one place, and what to call it.

    The hub relaying a device is the only thing the API says about where that
    device physically is - but it says it loosely. A device names the hub
    relaying it; a hub names nothing, or names itself; and a device with no hub
    at all says so in two different ways, an empty string and twelve zeros.
    Taken one device at a time, that reads as one group per thermometer, which
    is a picker nobody can choose from.

    So the account is read as a whole. A device is a hub when something else is
    relayed by it, or when SwitchBot types it as one - the second is what keeps
    a hub with nothing behind it yet in the list, and being wrong about it can
    only ever misplace a line in the picker, never change what is collected.
    Everything the cloud cannot place lands in one last group rather than in a
    group each.

    The same reading answers both questions, which is the point of it being one
    class: the picker asks which places there are, and the sync asks which
    devices are in the places that were ticked. Two rules could disagree, and
    then a thermometer would sit in a group the sync never looks in.
    """

    def __init__(self, devices: list[SwitchBotDevice]) -> None:
        self._devices = devices
        self._relayed = {device.hub_id for device in devices if device.hub_id}
        self._names = {device.device_id: device.name or device.device_type or device.device_id for device in devices}

    def groups(self) -> list[SwitchBotHub]:
        """Every place this account reaches into, each naming what stands in it."""
        members: dict[str, list[str]] = {}
        for device in self._devices:
            place = self.place(device)
            members.setdefault(place, [])
            # The hub heads its own line, so it is not also listed inside it -
            # although it is collected like any other, a Hub 2 being a
            # thermometer in its own right.
            if place != device.device_id:
                members[place].append(self._names[device.device_id])
        result = [
            SwitchBotHub(hub_id=place, name=self._name_of(place), devices=tuple(names))
            for place, names in members.items()
        ]
        # Named hubs first and alphabetically; the unplaceable ones last, since
        # they are the group somebody scrolls to rather than looks for.
        return sorted(result, key=lambda hub: (not hub.name, hub.name))

    def following(self, hub_ids: tuple[str, ...]) -> list[SwitchBotDevice]:
        """The devices standing in the places this house follows, and no others."""
        return [device for device in self._devices if self.place(device) in hub_ids]

    def _name_of(self, place: str) -> str:
        """What to call a place: the hub's name, its id, or nothing at all.

        A hub relaying this account's devices without being listed on it is
        still a hub, so it is named by its id rather than falling in with the
        unplaceable - which is the one group that deliberately has no name.
        """
        if place == Constants.switchbot_no_hub_id:
            return ""
        return self._names.get(place, place)

    def place(self, device: SwitchBotDevice) -> str:
        """Where this device stands: its hub, itself if it is one, or nowhere."""
        if device.hub_id:
            return device.hub_id
        if self.is_hub(device):
            return device.device_id
        return Constants.switchbot_no_hub_id

    def is_hub(self, device: SwitchBotDevice) -> bool:
        """Whether this device is a place rather than a thing standing in one."""
        if device.device_id in self._relayed:
            return True
        return Constants.switchbot_hub_type in device.device_type.lower()
