from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.switch_bot_hub import SwitchBotHub


def test_class() -> None:
    tested = SwitchBotHub
    fields = ["hub_id", "name", "devices"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SwitchBotHub, dict[str, Any]]] = [
        (
            SwitchBotHub(hub_id="FA7310762361", name="Hub Mini B2", devices=("Grenier 03", "Dehors 01")),
            {"hub_id": "FA7310762361", "name": "Hub Mini B2", "devices": ["Grenier 03", "Dehors 01"]},
        ),
        (SwitchBotHub(hub_id="none"), {"hub_id": "none", "name": "", "devices": []}),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SwitchBotHub
    tests: list[tuple[dict[str, Any], SwitchBotHub]] = [
        (
            {"hub_id": "FA7310762361", "name": "Hub Mini B2", "devices": ["Grenier 03", "Dehors 01"]},
            SwitchBotHub(hub_id="FA7310762361", name="Hub Mini B2", devices=("Grenier 03", "Dehors 01")),
        ),
        ({}, SwitchBotHub(hub_id="", name="", devices=())),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
