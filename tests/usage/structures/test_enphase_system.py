from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.enphase_system import EnphaseSystem


def test_class() -> None:
    tested = EnphaseSystem
    fields = ["system_id", "name", "status"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[EnphaseSystem, dict[str, str]]] = [
        (
            EnphaseSystem(system_id="3456789", name="Dougmar", status="normal"),
            {"system_id": "3456789", "name": "Dougmar", "status": "normal"},
        ),
        (EnphaseSystem(system_id="3456789"), {"system_id": "3456789", "name": "", "status": ""}),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = EnphaseSystem
    tests: list[tuple[dict[str, Any], EnphaseSystem]] = [
        (
            {"system_id": "3456789", "name": "Dougmar", "status": "normal"},
            EnphaseSystem(system_id="3456789", name="Dougmar", status="normal"),
        ),
        ({}, EnphaseSystem(system_id="", name="", status="")),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
