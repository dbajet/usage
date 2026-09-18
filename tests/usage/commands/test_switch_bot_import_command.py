from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest

from usage.commands.switch_bot_import_command import SwitchBotImportCommand
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample

PARIS = ZoneInfo("Europe/Paris")
PACIFIC = ZoneInfo("America/Los_Angeles")
SQL_HOUSES = "SELECT id, name_sealed AS name, timezone FROM houses ORDER BY id"
SQL_SENSORS = "SELECT id, name_sealed AS name, entity_id_sealed AS entity_id FROM sensors WHERE house_id = %s ORDER BY id"
SQL_INSERT = """
                    INSERT INTO samples(sensor_id, measured_at, value) VALUES (%s, %s, %s)
                    ON CONFLICT (sensor_id, measured_at) DO NOTHING
                    """
# The export as SwitchBot writes it: a row a minute whether or not anything
# moved, the unit in the header, and no offset anywhere.
EXPORT = """Date,Temperature_Celsius(℃),Relative_Humidity(%),DPT(℃),VPD(kPa),Abs Humidity(g/m³)
"Sep 1, 2026 07:56",22.5,71,17.0,0.79,14.18
"Sep 1, 2026 07:57",22.5,71,17.0,0.79,14.18
"Sep 1, 2026 07:58",22.6,71,17.1,0.79,14.28
"Sep 1, 2026 07:59",22.6,72,17.3,0.78,14.48
"""


def helper_instance() -> SwitchBotImportCommand:
    return SwitchBotImportCommand(MagicMock())


def helper_sensors() -> list[dict[str, Any]]:
    return [
        {"id": 13, "name": "Cave à vin 05", "entity_id": "switchbot.c271111ec0ab"},
        {"id": 14, "name": "Cave à vin 05 humidity", "entity_id": "switchbot.c271111ec0ab.humidity"},
        {"id": 15, "name": "Grenier 03", "entity_id": "switchbot.d382222fd1bc"},
    ]


def helper_export(tmp_path: Path, body: str = EXPORT, name: str = "Cave à vin 05_data.csv") -> Path:
    result = tmp_path / name
    result.write_text(body, encoding="utf-8")
    return result


def test___init__() -> None:
    database = MagicMock()
    tested = SwitchBotImportCommand(database)
    assert tested._database is database


@patch.object(SwitchBotImportCommand, "_store")
@patch.object(SwitchBotImportCommand, "_parse")
@patch.object(SwitchBotImportCommand, "_sensors")
@patch.object(SwitchBotImportCommand, "_house")
def test_run(house_of: MagicMock, sensors_of: MagicMock, parse: MagicMock, store: MagicMock, tmp_path: Path) -> None:
    tested = helper_instance()

    def reset_mocks() -> None:
        house_of.reset_mock()
        sensors_of.reset_mock()
        parse.reset_mock()
        store.reset_mock()

    path = helper_export(tmp_path)
    house = {"id": 3, "name": "Fremur", "timezone": "Europe/Paris"}
    readings = [
        SensorSample(entity_id="", name="", unit="°C", value=22.5, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="%", value=71.0, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="°C", value=22.6, measured_at=datetime(2026, 9, 1, 5, 57, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="%", value=71.0, measured_at=datetime(2026, 9, 1, 5, 57, tzinfo=UTC)),
    ]

    # the file names the device, so nothing has to be typed twice
    house_of.side_effect = [house]
    sensors_of.side_effect = [(13, 14)]
    parse.side_effect = [readings]
    store.side_effect = [2, 1]
    result = tested.run(path, "Fremur")
    expected = {
        "house": "Fremur",
        "sensor": "Cave à vin 05",
        "zone": "Europe/Paris",
        "rows": 4,
        "temperature": 2,
        "humidity": 1,
        "from": "2026-09-01T05:56:00+00:00",
        "to": "2026-09-01T05:57:00+00:00",
    }
    assert result == expected
    assert house_of.mock_calls == [call("Fremur")]
    assert sensors_of.mock_calls == [call(3, "Cave à vin 05")]
    assert parse.mock_calls == [call(path, PARIS)]
    exp_calls = [
        call(13, [readings[0], readings[2]]),
        call(14, [readings[1]]),
    ]
    assert store.mock_calls == exp_calls
    reset_mocks()

    # a sensor renamed since it arrived is named explicitly, and a thermometer
    # whose humidity was deleted stores the temperatures alone
    house_of.side_effect = [house]
    sensors_of.side_effect = [(13, 0)]
    parse.side_effect = [readings]
    store.side_effect = [2]
    result = tested.run(path, "Fremur", " The Cellar ")
    expected = {
        "house": "Fremur",
        "sensor": "The Cellar",
        "zone": "Europe/Paris",
        "rows": 4,
        "temperature": 2,
        "humidity": 0,
        "from": "2026-09-01T05:56:00+00:00",
        "to": "2026-09-01T05:57:00+00:00",
    }
    assert result == expected
    assert sensors_of.mock_calls == [call(3, "The Cellar")]
    assert store.mock_calls == [call(13, [readings[0], readings[2]])]
    assert house_of.mock_calls == [call("Fremur")]
    assert parse.mock_calls == [call(path, PARIS)]
    reset_mocks()

    # the phone that exported it was somewhere else, which is the ordinary case
    # for a house nobody was standing in
    house_of.side_effect = [house]
    sensors_of.side_effect = [(13, 14)]
    parse.side_effect = [readings]
    store.side_effect = [2, 1]
    result = tested.run(path, "Fremur", "", " America/Los_Angeles ")
    expected = {
        "house": "Fremur",
        "sensor": "Cave à vin 05",
        "zone": "America/Los_Angeles",
        "rows": 4,
        "temperature": 2,
        "humidity": 1,
        "from": "2026-09-01T05:56:00+00:00",
        "to": "2026-09-01T05:57:00+00:00",
    }
    assert result == expected
    assert parse.mock_calls == [call(path, PACIFIC)]
    assert house_of.mock_calls == [call("Fremur")]
    assert sensors_of.mock_calls == [call(3, "Cave à vin 05")]
    exp_calls = [
        call(13, [readings[0], readings[2]]),
        call(14, [readings[1]]),
    ]
    assert store.mock_calls == exp_calls
    reset_mocks()

    # a file with nothing in it
    house_of.side_effect = [house]
    sensors_of.side_effect = [(13, 14)]
    parse.side_effect = [[]]
    with pytest.raises(AppException) as exc_info:
        tested.run(path, "Fremur")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Cave à vin 05_data.csv carries no readings."
    assert store.mock_calls == []
    assert house_of.mock_calls == [call("Fremur")]
    assert sensors_of.mock_calls == [call(3, "Cave à vin 05")]
    assert parse.mock_calls == [call(path, PARIS)]
    reset_mocks()


def test__house() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    rows = [
        {"id": 1, "name": "Fremur", "timezone": "Europe/Paris"},
        {"id": 2, "name": "Dougmar", "timezone": "America/Los_Angeles"},
    ]
    exp_calls = [call.fetch_all(SQL_HOUSES), call.decrypt_rows(rows, ("name",))]

    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [rows]
    result = tested._house(" fremur ")
    assert result == rows[0]
    assert database.mock_calls == exp_calls
    reset_mocks()

    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [rows]
    with pytest.raises(AppException) as exc_info:
        tested._house("Nowhere")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "No house is called Nowhere."
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__sensors() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sensors = helper_sensors()
    exp_calls = [call.fetch_all(SQL_SENSORS, (3,)), call.decrypt_rows(sensors, ("name", "entity_id"))]

    # the thermometer, and the humidity collected beside it
    database.fetch_all.side_effect = [sensors]
    database.decrypt_rows.side_effect = [sensors]
    result = tested._sensors(3, "cave à vin 05")
    expected = (13, 14)
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a thermometer whose humidity sensor is not there
    database.fetch_all.side_effect = [sensors]
    database.decrypt_rows.side_effect = [sensors]
    result = tested._sensors(3, "Grenier 03")
    expected = (15, 0)
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()

    database.fetch_all.side_effect = [sensors]
    database.decrypt_rows.side_effect = [sensors]
    with pytest.raises(AppException) as exc_info:
        tested._sensors(3, "Nowhere")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "This house has no thermometer called Nowhere."
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a Home Assistant sensor, which keeps no history of this kind to import
    pushed = [{"id": 20, "name": "Garage", "entity_id": "sensor.garage_temperature"}]
    database.fetch_all.side_effect = [pushed]
    database.decrypt_rows.side_effect = [pushed]
    with pytest.raises(AppException) as exc_info:
        tested._sensors(3, "Garage")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Garage is not a SwitchBot thermometer."
    exp_pushed = [call.fetch_all(SQL_SENSORS, (3,)), call.decrypt_rows(pushed, ("name", "entity_id"))]
    assert database.mock_calls == exp_pushed
    reset_mocks()


def test__parse(tmp_path: Path) -> None:
    tested = helper_instance()

    result = tested._parse(helper_export(tmp_path), PARIS)
    expected = [
        SensorSample(entity_id="", name="", unit="°C", value=22.5, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="%", value=71.0, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="°C", value=22.5, measured_at=datetime(2026, 9, 1, 5, 57, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="%", value=71.0, measured_at=datetime(2026, 9, 1, 5, 57, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="°C", value=22.6, measured_at=datetime(2026, 9, 1, 5, 58, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="%", value=71.0, measured_at=datetime(2026, 9, 1, 5, 58, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="°C", value=22.6, measured_at=datetime(2026, 9, 1, 5, 59, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="%", value=72.0, measured_at=datetime(2026, 9, 1, 5, 59, tzinfo=UTC)),
    ]
    assert result == expected

    # an app set to Fahrenheit says so in the header, and is converted from what
    # it says rather than from what it was expected to say
    fahrenheit = '''Date,Temperature_Fahrenheit(℉),Relative_Humidity(%)
"Sep 1, 2026 07:56",79.0,71
'''
    result = tested._parse(helper_export(tmp_path, fahrenheit, "f.csv"), PARIS)
    expected = [
        SensorSample(entity_id="", name="", unit="°C", value=26.11, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="%", value=71.0, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
    ]
    assert result == expected

    # a row whose numbers are missing or unreadable, and a file with no humidity
    partial = '''Date,Temperature_Celsius(℃)
"Sep 1, 2026 07:56",22.5
"Sep 1, 2026 07:57",
"Sep 1, 2026 07:58",warm
'''
    result = tested._parse(helper_export(tmp_path, partial, "partial.csv"), PARIS)
    expected = [
        SensorSample(entity_id="", name="", unit="°C", value=22.5, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
    ]
    assert result == expected

    # a file that is not one of these at all
    other = "when,how warm\n2026-09-01,22.5\n"
    path = helper_export(tmp_path, other, "other.csv")
    with pytest.raises(AppException) as exc_info:
        tested._parse(path, PARIS)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "other.csv has no temperature column; its header reads when, how warm."


def test__sample() -> None:
    tested = helper_instance()
    result = tested._sample("°C", 22.456, datetime(2026, 9, 1, 5, 56, tzinfo=UTC))
    expected = SensorSample(entity_id="", name="", unit="°C", value=22.46, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC))
    assert result == expected


def test__collapse() -> None:
    tested = helper_instance()

    def helper_run(values: list[float]) -> list[float]:
        samples = [
            SensorSample(entity_id="", name="", unit="°C", value=value, measured_at=datetime(2026, 9, 1, 5, index, tzinfo=UTC))
            for index, value in enumerate(values)
        ]
        return [sample.value for sample in tested._collapse(samples)]

    tests: list[tuple[list[float], list[float]]] = [
        # a run is the instant it began, and a value that comes back is new again
        ([22.5, 22.5, 22.5, 22.6, 22.6, 22.5], [22.5, 22.6, 22.5]),
        ([22.5], [22.5]),
        ([], []),
    ]
    for values, expected in tests:
        result = helper_run(values)
        assert result == expected

    # the instant kept is the first of the run, not the last
    samples = [
        SensorSample(entity_id="", name="", unit="°C", value=22.5, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="°C", value=22.5, measured_at=datetime(2026, 9, 1, 5, 57, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="°C", value=22.6, measured_at=datetime(2026, 9, 1, 5, 58, tzinfo=UTC)),
    ]
    result = [sample.measured_at for sample in tested._collapse(samples)]
    expected = [datetime(2026, 9, 1, 5, 56, tzinfo=UTC), datetime(2026, 9, 1, 5, 58, tzinfo=UTC)]
    assert result == expected


def test__store() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    samples = [
        SensorSample(entity_id="", name="", unit="°C", value=22.5, measured_at=datetime(2026, 9, 1, 5, 56, tzinfo=UTC)),
        SensorSample(entity_id="", name="", unit="°C", value=22.6, measured_at=datetime(2026, 9, 1, 5, 58, tzinfo=UTC)),
    ]
    database.execute.side_effect = [1, 1]
    result = tested._store(13, samples)
    expected = 2
    assert result == expected
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(SQL_INSERT, (13, "2026-09-01T05:56:00+00:00", 22.5)),
        call.execute(SQL_INSERT, (13, "2026-09-01T05:58:00+00:00", 22.6)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    result = tested._store(13, [])
    assert result == 0
    assert database.mock_calls == []
    reset_mocks()


def test__column() -> None:
    tested = helper_instance()
    columns = ["Date", "Temperature_Celsius(℃)", "Relative_Humidity(%)", "DPT(℃)"]
    tests: list[tuple[str, str]] = [
        ("Temperature_", "Temperature_Celsius(℃)"),
        ("Relative_Humidity", "Relative_Humidity(%)"),
        ("Pressure", ""),
    ]
    for prefix, expected in tests:
        result = tested._column(columns, prefix)
        assert result == expected


def test__device_of() -> None:
    tested = helper_instance()
    tests: list[tuple[str, str]] = [
        ("Cave à vin 05_data.csv", "Cave à vin 05"),
        ("Dehors 01_data.csv", "Dehors 01"),
        # a file somebody renamed on the way out
        ("cellar.csv", "cellar"),
    ]
    for name, expected in tests:
        result = tested._device_of(Path("/tmp") / name)
        assert result == expected


def test__zone() -> None:
    tested = helper_instance()
    result = tested._zone("Europe/Paris")
    assert result == PARIS

    with pytest.raises(AppException) as exc_info:
        tested._zone("Middle/Earth")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The time zone Middle/Earth cannot be resolved."


def test__instant() -> None:
    tested = helper_instance()

    result = tested._instant("Sep 1, 2026 07:56", PARIS, None)
    expected = datetime(2026, 9, 1, 5, 56, tzinfo=UTC)
    assert result == expected

    # the autumn fall-back repeats an hour, and the rows are in order: a moment
    # that does not move forward is the second pass through it
    first = tested._instant("Oct 25, 2026 02:30", PARIS, datetime(2026, 10, 25, 0, 20, tzinfo=UTC))
    expected = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert first == expected
    second = tested._instant("Oct 25, 2026 02:30", PARIS, first)
    expected = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert second == expected

    # a third pass through the same minute is not something the clock does, so
    # it is read plainly rather than shifted again; the row collides with one
    # already stored and the insert lets it go
    result = tested._instant("Oct 25, 2026 02:30", PARIS, second)
    expected = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert result == expected

    # a file written in another language, which must not become a plausible date
    tests = ["1 sept. 2026 07:56", "", "2026-09-01 07:56"]
    for text in tests:
        with pytest.raises(AppException) as exc_info:
            tested._instant(text, PARIS, None)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == f"{text} is not a date this export should carry."


def test__celsius() -> None:
    tested = helper_instance()
    tests: list[tuple[float, bool, float]] = [
        (22.5, False, 22.5),
        (79.0, True, 26.11111111111111),
        (32.0, True, 0.0),
    ]
    for degrees, fahrenheit, expected in tests:
        result = tested._celsius(degrees, fahrenheit)
        assert result == expected


def test__number() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, float | None]] = [
        ("22.5", 22.5),
        (" 22.5 ", 22.5),
        ("71", 71.0),
        ("", None),
        ("   ", None),
        (None, None),
        ("warm", None),
    ]
    for raw, expected in tests:
        result = tested._number(raw)
        assert result == expected
