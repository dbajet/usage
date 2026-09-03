from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.ingest_request import IngestRequest
from usage.handlers.sample_input import SampleInput


def test_inheritance() -> None:
    tested = IngestRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = IngestRequest
    result = list(tested.model_fields.keys())
    expected = ["samples"]
    assert result == expected


def test___init__() -> None:
    tested = IngestRequest(
        samples=[
            SampleInput(
                entity_id="sensor.garage_temperature",
                value=84.9,
                name="Garage",
                unit="°F",
                measured_at="2026-09-02T23:16:59+00:00",
            ),
        ],
    )
    result = tested.model_dump()
    expected = {
        "samples": [
            {
                "entity_id": "sensor.garage_temperature",
                "value": 84.9,
                "name": "Garage",
                "unit": "°F",
                "measured_at": "2026-09-02T23:16:59+00:00",
            },
        ],
    }
    assert result == expected
