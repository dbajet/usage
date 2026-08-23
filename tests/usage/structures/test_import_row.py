from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.import_row import ImportRow


def test_class() -> None:
    tested = ImportRow
    fields = ["read_on", "edf", "gdf", "water", "hc", "hp"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[ImportRow, dict[str, str | float | None]]] = [
        (
            ImportRow(read_on="2026-01-15", edf=17431.0, gdf=9792.0, water=1450.0, hc=17273.0, hp=158.0),
            {"read_on": "2026-01-15", "edf": 17431.0, "gdf": 9792.0, "water": 1450.0, "hc": 17273.0, "hp": 158.0},
        ),
        (
            ImportRow(read_on="2023-07-15", edf=11282.0, gdf=5530.0, water=1247.0, hc=None, hp=None),
            {"read_on": "2023-07-15", "edf": 11282.0, "gdf": 5530.0, "water": 1247.0, "hc": None, "hp": None},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = ImportRow
    tests: list[tuple[dict[str, Any], ImportRow]] = [
        (
            {"read_on": "2026-01-15", "edf": 17431, "gdf": 9792, "water": 1450, "hc": 17273, "hp": 158},
            ImportRow(read_on="2026-01-15", edf=17431.0, gdf=9792.0, water=1450.0, hc=17273.0, hp=158.0),
        ),
        (
            {},
            ImportRow(read_on="", edf=0.0, gdf=0.0, water=0.0, hc=None, hp=None),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
