from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.import_command import ImportCommand
from usage.structures.app_exception import AppException
from usage.structures.import_row import ImportRow


def helper_instance() -> ImportCommand:
    return ImportCommand(MagicMock())


def test___init__() -> None:
    database = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()

    tested = ImportCommand(database)
    assert tested._database is database
    assert database.mock_calls == []
    reset_mocks()


@patch.object(ImportCommand, "_import_split")
@patch.object(ImportCommand, "_import_simple")
@patch.object(ImportCommand, "_insert_meter")
@patch.object(ImportCommand, "_parse")
@patch.object(ImportCommand, "_house_exists")
def test_run(
    house_exists: MagicMock,
    parse: MagicMock,
    insert_meter: MagicMock,
    import_simple: MagicMock,
    import_split: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        house_exists.reset_mock()
        parse.reset_mock()
        insert_meter.reset_mock()
        import_simple.reset_mock()
        import_split.reset_mock()
        database.reset_mock()

    rows = [
        ImportRow(read_on="2023-07-15", edf=11282.0, gdf=5530.0, water=1247.0, hc=None, hp=None),
        ImportRow(read_on="2023-08-15", edf=11387.0, gdf=5549.0, water=1251.0, hc=None, hp=None),
    ]

    # the house was already imported
    house_exists.side_effect = [True]
    with pytest.raises(AppException) as exc_info:
        tested.run(Path("/tmp/fremur.csv"), "Fremur")
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "The house 'Fremur' already exists - the history was probably imported."
    assert house_exists.mock_calls == [call("Fremur")]
    assert parse.mock_calls == []
    assert insert_meter.mock_calls == []
    assert import_simple.mock_calls == []
    assert import_split.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # happy path
    house_exists.side_effect = [False]
    parse.side_effect = [({"edf": 11240.0, "gdf": 5519.0, "water": 1242.0}, rows)]
    database.encrypt.side_effect = ["sealedFremur"]
    database.execute.side_effect = [3]
    insert_meter.side_effect = [9, 10, 11]
    import_split.side_effect = [(3, 26, 27)]
    import_simple.side_effect = [(1, 24, 24), (2, 24, 24)]
    result = tested.run(Path("/tmp/fremur.csv"), "Fremur")
    expected = {"house": "Fremur", "meters": 3, "registers": 6, "readings": 74, "values": 75}
    assert result == expected
    assert house_exists.mock_calls == [call("Fremur")]
    assert parse.mock_calls == [call(Path("/tmp/fremur.csv"))]
    exp_calls = [
        call(3, "electricity", "EDF", "kWh", 0),
        call(3, "gas", "GDF", "m3", 1),
        call(3, "water", "Water", "m3", 2),
    ]
    assert insert_meter.mock_calls == exp_calls
    exp_calls = [call(9, 11240.0, rows)]
    assert import_split.mock_calls == exp_calls
    exp_calls = [
        call(10, 5519.0, [("2023-07-15", 5530.0), ("2023-08-15", 5549.0)]),
        call(11, 1242.0, [("2023-07-15", 1247.0), ("2023-08-15", 1251.0)]),
    ]
    assert import_simple.mock_calls == exp_calls
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        call.encrypt("Fremur"),
        call.execute("INSERT INTO houses(name_sealed) VALUES (%s) RETURNING id", ("sealedFremur",)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__house_exists() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sealed_rows = [{"id": 1, "name": "sealedFremur"}]
    tests = [
        ("Fremur", True),
        (" fremur ", True),
        ("Dougmar", False),
    ]
    for house_name, expected in tests:
        database.fetch_all.side_effect = [sealed_rows]
        database.decrypt_rows.side_effect = [[{"id": 1, "name": "Fremur"}]]
        result = tested._house_exists(house_name)
        assert result is expected, f"---> {house_name}"
        exp_calls = [
            call.fetch_all("SELECT id, name_sealed AS name FROM houses ORDER BY id"),
            call.decrypt_rows(sealed_rows, ("name",)),
        ]
        assert database.mock_calls == exp_calls
        reset_mocks()


def test__parse(tmp_path: Path) -> None:
    tested = helper_instance()
    content = "\n".join([
        "\tconsommation\t\t\t\t\t\tcompteur",
        "\tEDF\tGDF\tWater\t\t\t\tEDF\tGDF\tWater",
        "Arrivee\t\t\t\t\t\t\t11240\t5519\t1242",
        "",
        "Jul-2023\t42\t11\t5\t\t\t\t11282\t5530\t1247",
        "Aug-2023\t105\t19\t4\tas of 2023-08-15\t\t\t11387\t5549\t1251",
        "Dec-2025\t206\t392\t9\t\tHC\tHP\t17177\t9375\t1443",
        "Jan-2026\t254\t417\t7\t\t17273\t158\t17431\t9792\t1450",
        "Sep-2024\t376\t4\t602\t\t375.6\t35968\t37619\t8306\t8920",
        "Aug-2026\t0\t0\t0",
        "not-a-month\t1\t2\t3\t\t\t\t1\t2\t3",
    ])
    csv_path = tmp_path / "history.csv"
    csv_path.write_text(content, encoding="utf-8")
    result = tested._parse(csv_path)
    expected = (
        {"edf": 11240.0, "gdf": 5519.0, "water": 1242.0},
        [
            ImportRow(read_on="2023-07-15", edf=11282.0, gdf=5530.0, water=1247.0, hc=None, hp=None),
            ImportRow(read_on="2023-08-15", edf=11387.0, gdf=5549.0, water=1251.0, hc=None, hp=None),
            ImportRow(read_on="2025-12-15", edf=17177.0, gdf=9375.0, water=1443.0, hc=None, hp=None),
            ImportRow(read_on="2026-01-15", edf=17431.0, gdf=9792.0, water=1450.0, hc=17273.0, hp=158.0),
            # enphase measurements share the HC/HP columns but do not sum to the counter
            ImportRow(read_on="2024-09-15", edf=37619.0, gdf=8306.0, water=8920.0, hc=None, hp=None),
        ],
    )
    assert result == expected


@patch.object(ImportCommand, "_insert_value")
@patch.object(ImportCommand, "_insert_reading")
@patch.object(ImportCommand, "_insert_register")
def test__import_simple(insert_register: MagicMock, insert_reading: MagicMock, insert_value: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        insert_register.reset_mock()
        insert_reading.reset_mock()
        insert_value.reset_mock()
        database.reset_mock()

    # a counter drop starts a replacement register (Dougmar's water meter)
    insert_register.side_effect = [21, 22]
    insert_reading.side_effect = [31, 32, 33]
    result = tested._import_simple(11, 87924.0, [("2015-09-15", 88092.0), ("2015-10-15", 276.0), ("2015-11-15", 542.0)])
    expected = (2, 3, 3)
    assert result == expected
    exp_calls = [call(11, "", 87924.0, 0, True), call(11, "", 0.0, 1, True)]
    assert insert_register.mock_calls == exp_calls
    exp_calls = [call(11, "2015-09-15"), call(11, "2015-10-15"), call(11, "2015-11-15")]
    assert insert_reading.mock_calls == exp_calls
    exp_calls = [call(31, 21, 88092.0), call(32, 22, 276.0), call(33, 22, 542.0)]
    assert insert_value.mock_calls == exp_calls
    exp_calls = [call.execute("UPDATE registers SET active = false WHERE id = %s", (21,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # no reading at all still creates the register
    insert_register.side_effect = [21]
    result = tested._import_simple(11, 0.0, [])
    expected = (1, 0, 0)
    assert result == expected
    exp_calls = [call(11, "", 0.0, 0, True)]
    assert insert_register.mock_calls == exp_calls
    assert insert_reading.mock_calls == []
    assert insert_value.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()


@patch.object(ImportCommand, "_insert_value")
@patch.object(ImportCommand, "_insert_reading")
@patch.object(ImportCommand, "_insert_register")
@patch.object(ImportCommand, "_import_simple")
def test__import_split(
    import_simple: MagicMock,
    insert_register: MagicMock,
    insert_reading: MagicMock,
    insert_value: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        import_simple.reset_mock()
        insert_register.reset_mock()
        insert_reading.reset_mock()
        insert_value.reset_mock()
        database.reset_mock()

    rows = [
        ImportRow(read_on="2025-12-15", edf=17177.0, gdf=9375.0, water=1443.0, hc=None, hp=None),
        ImportRow(read_on="2026-01-15", edf=17431.0, gdf=9792.0, water=1450.0, hc=17273.0, hp=158.0),
        ImportRow(read_on="2026-02-15", edf=17564.0, gdf=10062.0, water=1455.0, hc=17273.0, hp=291.0),
    ]

    # no split month: plain single-register import
    import_simple.side_effect = [(1, 2, 2)]
    result = tested._import_split(9, 11240.0, rows[:1])
    expected = (1, 2, 2)
    assert result == expected
    exp_calls = [call(9, 11240.0, [("2025-12-15", 17177.0)])]
    assert import_simple.mock_calls == exp_calls
    assert insert_register.mock_calls == []
    assert insert_reading.mock_calls == []
    assert insert_value.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # the HC/HP columns appear: the summed register stops on the first split
    # month, whose values become the baselines of the two new registers
    import_simple.side_effect = [(1, 2, 2)]
    insert_register.side_effect = [23, 24]
    insert_reading.side_effect = [41]
    result = tested._import_split(9, 11240.0, rows)
    expected = (3, 3, 4)
    assert result == expected
    exp_calls = [call(9, 11240.0, [("2025-12-15", 17177.0), ("2026-01-15", 17431.0)])]
    assert import_simple.mock_calls == exp_calls
    exp_calls = [call(9, "HC", 17273.0, 1, True), call(9, "HP", 158.0, 2, True)]
    assert insert_register.mock_calls == exp_calls
    exp_calls = [call(9, "2026-02-15")]
    assert insert_reading.mock_calls == exp_calls
    exp_calls = [call(41, 23, 17273.0), call(41, 24, 291.0)]
    assert insert_value.mock_calls == exp_calls
    exp_calls = [call.execute("UPDATE registers SET active = false WHERE meter_id = %s", (9,))]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__insert_meter() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.encrypt.side_effect = ["sealedEDF"]
    database.execute.side_effect = [9]
    result = tested._insert_meter(3, "electricity", "EDF", "kWh", 0)
    expected = 9
    assert result == expected
    exp_calls = [
        call.encrypt("EDF"),
        call.execute(
            "INSERT INTO meters(house_id, kind, label_sealed, unit, position) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (3, "electricity", "sealedEDF", "kWh", 0),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__insert_register() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.encrypt.side_effect = ["sealedHC"]
    database.execute.side_effect = [23]
    result = tested._insert_register(9, "HC", 17273.0, 1, True)
    expected = 23
    assert result == expected
    exp_calls = [
        call.encrypt("HC"),
        call.execute(
            """
            INSERT INTO registers(meter_id, label_sealed, initial_value, position, active)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (9, "sealedHC", 17273.0, 1, True),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__insert_reading() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.execute.side_effect = [41]
    result = tested._insert_reading(9, "2026-02-15")
    expected = 41
    assert result == expected
    exp_calls = [
        call.execute(
            "INSERT INTO readings(meter_id, read_on, source) VALUES (%s, %s, %s) RETURNING id",
            (9, "2026-02-15", "import"),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__insert_value() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.execute.side_effect = [0]
    result = tested._insert_value(41, 23, 17273.0)
    assert result is None
    exp_calls = [
        call.execute(
            "INSERT INTO reading_values(reading_id, register_id, value) VALUES (%s, %s, %s)",
            (41, 23, 17273.0),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__month_date() -> None:
    tested = helper_instance()
    tests = [
        ("Jul-2023", "2023-07-15"),
        ("Jan-2026", "2026-01-15"),
        ("Arrivee", ""),
        ("", ""),
    ]
    for value, expected in tests:
        result = tested._month_date(value)
        assert result == expected, f"---> {value}"


def test__number() -> None:
    tested = helper_instance()
    tests = [
        ("17273", 17273.0),
        (" 298.6 ", 298.6),
        ("HC", None),
        ("", None),
    ]
    for value, expected in tests:
        result = tested._number(value)
        assert result == expected, f"---> {value}"
