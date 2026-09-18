from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.sensor_state import SensorState


def test_class() -> None:
    tested = SensorState
    fields = ["entity_hash", "value", "measured_at", "battery"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SensorState, dict[str, Any]]] = [
        (
            SensorState(
                entity_hash="theHash",
                value=19.4,
                measured_at=datetime(2026, 9, 17, 14, 2, tzinfo=UTC),
                battery=87,
            ),
            {"entity_hash": "theHash", "value": 19.4, "measured_at": "2026-09-17T14:02:00+00:00", "battery": 87},
        ),
        (
            SensorState(entity_hash="theHash"),
            {"entity_hash": "theHash", "value": None, "measured_at": None, "battery": None},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SensorState
    tests: list[tuple[dict[str, Any], SensorState]] = [
        (
            {"entity_hash": "theHash", "value": "19.4", "measured_at": "2026-09-17T14:02:00+00:00", "battery": "87"},
            SensorState(
                entity_hash="theHash",
                value=19.4,
                measured_at=datetime(2026, 9, 17, 14, 2, tzinfo=UTC),
                battery=87,
            ),
        ),
        ({}, SensorState(entity_hash="", value=None, measured_at=None, battery=None)),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
