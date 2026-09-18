from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.switch_bot_device import SwitchBotDevice


def test_class() -> None:
    tested = SwitchBotDevice
    fields = ["device_id", "name", "device_type", "hub_id"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SwitchBotDevice, dict[str, str]]] = [
        (
            SwitchBotDevice(device_id="C271111EC0AB", name="Grenier", device_type="Meter", hub_id="FA7310762361"),
            {"device_id": "C271111EC0AB", "name": "Grenier", "device_type": "Meter", "hub_id": "FA7310762361"},
        ),
        (
            SwitchBotDevice(device_id="C271111EC0AB"),
            {"device_id": "C271111EC0AB", "name": "", "device_type": "", "hub_id": ""},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SwitchBotDevice
    tests: list[tuple[dict[str, Any], SwitchBotDevice]] = [
        (
            {"device_id": "C271111EC0AB", "name": "Grenier", "device_type": "Meter", "hub_id": "FA7310762361"},
            SwitchBotDevice(device_id="C271111EC0AB", name="Grenier", device_type="Meter", hub_id="FA7310762361"),
        ),
        ({}, SwitchBotDevice(device_id="", name="", device_type="", hub_id="")),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
