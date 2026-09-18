from __future__ import annotations

from usage.libraries.switch_bot_hubs import SwitchBotHubs
from usage.structures.switch_bot_device import SwitchBotDevice
from usage.structures.switch_bot_hub import SwitchBotHub

# One real account holding two houses, as the cloud actually answers for it: a
# hub relaying six devices, a hub relaying nothing yet, three devices naming no
# hub with twelve zeros and three more naming none with an empty string.
HUB = "FA7310762361"
SPARE = "BB2210762399"


def helper_devices() -> list[SwitchBotDevice]:
    return [
        SwitchBotDevice(device_id="C2711101", name="Grenier 03", device_type="Meter", hub_id=HUB),
        SwitchBotDevice(device_id="C2711102", name="Dehors 01", device_type="WoIOSensor", hub_id=HUB),
        SwitchBotDevice(device_id="C2711103", name="Cave à vin 05", device_type="Meter", hub_id=HUB),
        SwitchBotDevice(device_id="C2711104", name="Frigidaire 06", device_type="Meter", hub_id=HUB),
        SwitchBotDevice(device_id="C2711105", name="RDC 04", device_type="Meter", hub_id=HUB),
        SwitchBotDevice(device_id="C2711106", name="Bureau Denis", device_type="Meter", hub_id=HUB),
        # the hub itself, which names no hub of its own and is a thermometer too
        SwitchBotDevice(device_id=HUB, name="Hub Mini B2", device_type="Hub Mini", hub_id=""),
        # a hub with nothing behind it yet: known by its type alone
        SwitchBotDevice(device_id=SPARE, name="SwitchBotHub", device_type="Hub 2", hub_id=""),
        SwitchBotDevice(device_id="D3822201", name="Router #1", device_type="Meter", hub_id=""),
        SwitchBotDevice(device_id="D3822202", name="Garage #2", device_type="Meter", hub_id=""),
        SwitchBotDevice(device_id="D3822203", name="Freezer #6", device_type="MeterPlus", hub_id=""),
    ]


def helper_instance() -> SwitchBotHubs:
    return SwitchBotHubs(helper_devices())


def test___init__() -> None:
    devices = helper_devices()
    tested = SwitchBotHubs(devices)
    assert tested._devices is devices
    assert tested._relayed == {HUB}
    assert tested._names["C2711101"] == "Grenier 03"


def test_groups() -> None:
    tested = helper_instance()
    result = tested.groups()
    expected = [
        # the hub heads its own line and is not listed inside it
        SwitchBotHub(
            hub_id=HUB,
            name="Hub Mini B2",
            devices=("Grenier 03", "Dehors 01", "Cave à vin 05", "Frigidaire 06", "RDC 04", "Bureau Denis"),
        ),
        SwitchBotHub(hub_id=SPARE, name="SwitchBotHub", devices=()),
        # one group for everything the cloud cannot place, not a group each
        SwitchBotHub(hub_id="none", name="", devices=("Router #1", "Garage #2", "Freezer #6")),
    ]
    assert result == expected

    # a device with no name of its own falls back to its type, then to its id
    tested = SwitchBotHubs(
        [
            SwitchBotDevice(device_id="C2711101", device_type="Meter", hub_id=HUB),
            SwitchBotDevice(device_id="C2711102", hub_id=HUB),
            SwitchBotDevice(device_id=HUB, hub_id=""),
        ],
    )
    result = tested.groups()
    expected = [SwitchBotHub(hub_id=HUB, name=HUB, devices=("Meter", "C2711102"))]
    assert result == expected

    tested = SwitchBotHubs([])
    assert tested.groups() == []


def test_following() -> None:
    tested = helper_instance()
    devices = helper_devices()

    # the hub's six devices and the hub itself; the other house's, never
    result = tested.following((HUB,))
    expected = [*devices[0:6], devices[6]]
    assert result == expected

    # the unplaceable group is followed by the one name they all answer to
    result = tested.following(("none",))
    expected = [devices[8], devices[9], devices[10]]
    assert result == expected

    result = tested.following((HUB, SPARE))
    expected = [*devices[0:6], devices[6], devices[7]]
    assert result == expected

    result = tested.following(())
    assert result == []


def test_place() -> None:
    tested = helper_instance()
    devices = helper_devices()
    tests: list[tuple[SwitchBotDevice, str]] = [
        # relayed: the hub it names
        (devices[0], HUB),
        # a hub naming no hub of its own: itself, so it stands in its own place
        (devices[6], HUB),
        (devices[7], SPARE),
        # everything else the cloud cannot place
        (devices[8], "none"),
    ]
    for device, expected in tests:
        result = tested.place(device)
        assert result == expected


def test_is_hub() -> None:
    tested = helper_instance()
    devices = helper_devices()
    tests: list[tuple[SwitchBotDevice, bool]] = [
        # something is relayed by it
        (devices[6], True),
        # nothing is, but SwitchBot types it as one
        (devices[7], True),
        (devices[0], False),
        (devices[10], False),
    ]
    for device, expected in tests:
        result = tested.is_hub(device)
        assert result is expected
