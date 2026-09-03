from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.sensor_command import SensorCommand
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample
from usage.structures.session_user import SessionUser


def helper_instance() -> SensorCommand:
    return SensorCommand(MagicMock())


def helper_user(is_admin: bool = False) -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane", is_admin=is_admin)


def helper_sample(entity_id: str = "sensor.garage_temperature", value: float = 84.9) -> SensorSample:
    return SensorSample(
        entity_id=entity_id,
        name="Garage",
        unit="°F",
        value=value,
        measured_at=datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC),
    )


def test___init__() -> None:
    database = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()

    tested = SensorCommand(database)
    assert tested._database is database
    assert database.mock_calls == []
    reset_mocks()


@patch.object(SensorCommand, "_find_or_create_sensor")
@patch.object(SensorCommand, "_parse_sample")
@patch.object(SensorCommand, "_house_from_token")
def test_ingest(house_from_token: MagicMock, parse_sample: MagicMock, find_or_create_sensor: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        house_from_token.reset_mock()
        parse_sample.reset_mock()
        find_or_create_sensor.reset_mock()
        database.reset_mock()

    exp_upsert = """
                    INSERT INTO samples(sensor_id, measured_at, value) VALUES (%s, %s, %s)
                    ON CONFLICT (sensor_id, measured_at) DO UPDATE SET value = EXCLUDED.value
                    """

    # too many samples
    house_from_token.side_effect = [3]
    with pytest.raises(AppException) as exc_info:
        tested.ingest("Bearer the-token", {"samples": [{"entity_id": "sensor.x", "value": 1}] * 1001})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "At most 1000 samples per request."
    assert house_from_token.mock_calls == [call("Bearer the-token")]
    assert parse_sample.mock_calls == []
    assert find_or_create_sensor.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # empty batch
    house_from_token.side_effect = [3]
    result = tested.ingest("Bearer the-token", {})
    expected = {"accepted": 0, "created": 0}
    assert result == expected
    assert house_from_token.mock_calls == [call("Bearer the-token")]
    assert parse_sample.mock_calls == []
    assert find_or_create_sensor.mock_calls == []
    exp_calls = [call.transaction(), call.transaction().__enter__(), call.transaction().__exit__(None, None, None)]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # two sensors, one of them new and sent twice: looked up once
    garage = helper_sample()
    garage_later = helper_sample(value=85.1)
    freezer = helper_sample(entity_id="sensor.freezer_temperature", value=-0.58)
    raw = [{"entity_id": "garage"}, {"entity_id": "freezer"}, {"entity_id": "garage-later"}]
    house_from_token.side_effect = [3]
    parse_sample.side_effect = [garage, freezer, garage_later]
    find_or_create_sensor.side_effect = [(9, False), (10, True)]
    database.execute.side_effect = [0, 0, 0]
    result = tested.ingest("Bearer the-token", {"samples": raw})
    expected = {"accepted": 3, "created": 1}
    assert result == expected
    assert house_from_token.mock_calls == [call("Bearer the-token")]
    assert parse_sample.mock_calls == [call(raw[0]), call(raw[1]), call(raw[2])]
    assert find_or_create_sensor.mock_calls == [call(3, garage), call(3, freezer)]
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(exp_upsert, (9, "2026-09-02T23:16:59+00:00", 84.9)),
        call.execute(exp_upsert, (10, "2026-09-02T23:16:59+00:00", -0.58)),
        call.execute(exp_upsert, (9, "2026-09-02T23:16:59+00:00", 85.1)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(SensorCommand, "_hash")
@patch("usage.commands.sensor_command.secrets")
def test_issue_token(secrets: MagicMock, hash_method: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        secrets.reset_mock()
        hash_method.reset_mock()
        database.reset_mock()

    # not an admin
    with pytest.raises(AppException) as exc_info:
        tested.issue_token(helper_user(), 3)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Only admins can do this."
    assert secrets.mock_calls == []
    assert hash_method.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.issue_token(helper_user(is_admin=True), 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert secrets.mock_calls == []
    assert hash_method.mock_calls == []
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()

    # happy path: the token is returned once, only its hash is stored
    database.fetch_one.side_effect = [{"id": 3}]
    database.execute.side_effect = [0]
    secrets.token_urlsafe.side_effect = ["the-token"]
    hash_method.side_effect = ["the-hash"]
    result = tested.issue_token(helper_user(is_admin=True), 3)
    expected = {"token": "the-token"}
    assert result == expected
    assert secrets.mock_calls == [call.token_urlsafe(32)]
    assert hash_method.mock_calls == [call("the-token")]
    exp_calls = [
        call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,)),
        call.execute("UPDATE houses SET ingest_token_hash = %s WHERE id = %s", ("the-hash", 3)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(SensorCommand, "_require_house")
def test_list_sensors(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    latest = [{"sensor_id": 9, "measured_at": datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC), "value": Decimal("84.90")}]
    sensor_rows = [
        {"id": 9, "entity_id": "sealedGarage", "name": "sealedGarageName", "unit": "°F", "position": 0, "active": True},
        {"id": 10, "entity_id": "sealedFreezer", "name": "sealedFreezerName", "unit": "°F", "position": 1, "active": False},
    ]
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [latest, sensor_rows]
    database.decrypt_rows.side_effect = [
        [
            {"id": 9, "entity_id": "sensor.garage_temperature", "name": "Garage", "unit": "°F", "position": 0, "active": True},
            {"id": 10, "entity_id": "sensor.freezer_temperature", "name": "Freezer", "unit": "°F", "position": 1, "active": False},
        ],
    ]
    result = tested.list_sensors(user, 3)
    expected = {
        "sensors": [
            {
                "id": 9,
                "entity_id": "sensor.garage_temperature",
                "name": "Garage",
                "unit": "°F",
                "position": 0,
                "active": True,
                "last_value": 84.9,
                "last_at": "2026-09-02T23:16:59+00:00",
            },
            {
                "id": 10,
                "entity_id": "sensor.freezer_temperature",
                "name": "Freezer",
                "unit": "°F",
                "position": 1,
                "active": False,
                "last_value": None,
                "last_at": "",
            },
        ],
    }
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.fetch_all(
            """
            SELECT DISTINCT ON (samples.sensor_id) samples.sensor_id, samples.measured_at, samples.value
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s
            ORDER BY samples.sensor_id, samples.measured_at DESC
            """,
            (3,),
        ),
        call.fetch_all(
            """
                SELECT id, entity_id_sealed AS entity_id, name_sealed AS name, unit, position, active
                FROM sensors WHERE house_id = %s ORDER BY position, id
                """,
            (3,),
        ),
        call.decrypt_rows(sensor_rows, ("entity_id", "name")),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(SensorCommand, "_require_sensor")
def test_update_sensor(require_sensor: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_sensor.reset_mock()
        database.reset_mock()

    user = helper_user()

    # the name is required
    require_sensor.side_effect = [{"id": 9, "house_id": 3}]
    with pytest.raises(AppException) as exc_info:
        tested.update_sensor(user, 9, {"name": "  ", "unit": "°F", "active": True})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter a sensor name."
    assert require_sensor.mock_calls == [call(user, 9)]
    assert database.mock_calls == []
    reset_mocks()

    # happy path
    require_sensor.side_effect = [{"id": 9, "house_id": 3}]
    database.encrypt.side_effect = ["sealedGarage"]
    database.execute.side_effect = [0]
    result = tested.update_sensor(user, 9, {"name": " Garage ", "unit": " °C ", "active": False})
    expected = {"message": "Sensor updated."}
    assert result == expected
    assert require_sensor.mock_calls == [call(user, 9)]
    exp_calls = [
        call.encrypt("Garage"),
        call.execute(
            "UPDATE sensors SET name_sealed = %s, unit = %s, active = %s WHERE id = %s",
            ("sealedGarage", "°C", False, 9),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(SensorCommand, "_require_house")
def test_set_order(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()

    # the list must be a permutation of the house sensors
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [[{"id": 9}, {"id": 10}, {"id": 11}]]
    with pytest.raises(AppException) as exc_info:
        tested.set_order(user, {"house_id": 3, "sensor_ids": [11, 9]})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The order must include every sensor of the house exactly once."
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [call.fetch_all("SELECT id FROM sensors WHERE house_id = %s ORDER BY id", (3,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path: the order is shared by the house
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [[{"id": 9}, {"id": 10}, {"id": 11}]]
    database.execute.side_effect = [0, 0, 0]
    result = tested.set_order(user, {"house_id": 3, "sensor_ids": [11, 9, 10]})
    expected = {"message": "Sensor order saved."}
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.fetch_all("SELECT id FROM sensors WHERE house_id = %s ORDER BY id", (3,)),
        call.transaction(),
        call.transaction().__enter__(),
        call.execute("UPDATE sensors SET position = %s WHERE id = %s", (0, 11)),
        call.execute("UPDATE sensors SET position = %s WHERE id = %s", (1, 9)),
        call.execute("UPDATE sensors SET position = %s WHERE id = %s", (2, 10)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.sensor_command.datetime", wraps=datetime)
@patch.object(SensorCommand, "_require_house")
def test_series(require_house: MagicMock, mock_datetime: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        mock_datetime.reset_mock()
        database.reset_mock()

    user = helper_user()
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)

    # unknown range
    require_house.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.series(user, 3, 14)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The range must be one of 1, 7, 30, 365 days."
    assert require_house.mock_calls == [call(user, 3)]
    assert mock_datetime.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # a week, hourly buckets; a sensor without samples is left out
    sensor_rows = [{"id": 9, "name": "sealedGarage", "unit": "°F"}, {"id": 10, "name": "sealedFreezer", "unit": "°F"}]
    rows = [
        {
            "sensor_id": 9,
            "bucket": datetime(2026, 9, 2, 22, 0, tzinfo=UTC),
            "average": Decimal("84.4567"),
            "low": Decimal("83.10"),
            "high": Decimal("85.90"),
        },
        {
            "sensor_id": 9,
            "bucket": datetime(2026, 9, 2, 23, 0, tzinfo=UTC),
            "average": Decimal("84.90"),
            "low": Decimal("84.90"),
            "high": Decimal("84.90"),
        },
    ]
    require_house.side_effect = [None]
    mock_datetime.now.side_effect = [now]
    database.fetch_all.side_effect = [sensor_rows, rows]
    database.decrypt_rows.side_effect = [[{"id": 9, "name": "Garage", "unit": "°F"}, {"id": 10, "name": "Freezer", "unit": "°F"}]]
    result = tested.series(user, 3, 7)
    expected = {
        "days": 7,
        "bucket_minutes": 60,
        "series": [
            {
                "sensor_id": 9,
                "name": "Garage",
                "unit": "°F",
                "points": [
                    {"at": "2026-09-02T22:00:00+00:00", "average": 84.46, "low": 83.1, "high": 85.9},
                    {"at": "2026-09-02T23:00:00+00:00", "average": 84.9, "low": 84.9, "high": 84.9},
                ],
            },
        ],
    }
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    assert mock_datetime.mock_calls == [call.now(UTC)]
    exp_calls = [
        call.fetch_all(
            "SELECT id, name_sealed AS name, unit FROM sensors WHERE house_id = %s AND active ORDER BY position, id",
            (3,),
        ),
        call.decrypt_rows(sensor_rows, ("name",)),
        call.fetch_all(
            """
            SELECT samples.sensor_id,
                   date_bin(%s, samples.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   AVG(samples.value) AS average, MIN(samples.value) AS low, MAX(samples.value) AS high
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s AND sensors.active AND samples.measured_at >= %s
            GROUP BY samples.sensor_id, bucket
            ORDER BY samples.sensor_id, bucket
            """,
            (timedelta(minutes=60), 3, "2026-08-27T12:00:00+00:00"),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__find_or_create_sensor() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sample = helper_sample()
    exp_insert = """
            INSERT INTO sensors(house_id, entity_id_sealed, entity_hash, name_sealed, unit, position)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """

    # known entity
    database.blind_index.side_effect = ["the-hash"]
    database.fetch_one.side_effect = [{"id": 9}]
    result = tested._find_or_create_sensor(3, sample)
    expected = (9, False)
    assert result == expected
    exp_calls = [
        call.blind_index("sensor.garage_temperature"),
        call.fetch_one("SELECT id FROM sensors WHERE house_id = %s AND entity_hash = %s", (3, "the-hash")),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # new entity: appended after the existing sensors
    tests = [({"count": 4}, 4), (None, 0)]
    for count_row, position in tests:
        database.blind_index.side_effect = ["the-hash"]
        database.fetch_one.side_effect = [None, count_row]
        database.encrypt.side_effect = ["sealedEntity", "sealedName"]
        database.execute.side_effect = [10]
        result = tested._find_or_create_sensor(3, sample)
        expected = (10, True)
        assert result == expected
        exp_calls = [
            call.blind_index("sensor.garage_temperature"),
            call.fetch_one("SELECT id FROM sensors WHERE house_id = %s AND entity_hash = %s", (3, "the-hash")),
            call.fetch_one("SELECT COUNT(*) AS count FROM sensors WHERE house_id = %s", (3,)),
            call.encrypt("sensor.garage_temperature"),
            call.encrypt("Garage"),
            call.execute(exp_insert, (3, "sealedEntity", "the-hash", "sealedName", "°F", position)),
        ]
        assert database.mock_calls == exp_calls
        reset_mocks()


@patch.object(SensorCommand, "_parse_instant")
def test__parse_sample(parse_instant: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        parse_instant.reset_mock()
        database.reset_mock()

    instant = datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC)

    # missing entity
    with pytest.raises(AppException) as exc_info:
        tested._parse_sample({"value": 84.9})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Each sample needs an entity_id."
    assert parse_instant.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # values that are not numbers
    for value in ["hot", float("nan"), float("inf")]:
        with pytest.raises(AppException) as exc_info:
            tested._parse_sample({"entity_id": "sensor.garage_temperature", "value": value})
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The value of sensor.garage_temperature is not a number."
        assert parse_instant.mock_calls == []
        assert database.mock_calls == []
        reset_mocks()

    # happy paths: the name falls back to the entity id, the value is rounded
    tests = [
        (
            {
                "entity_id": " Sensor.Garage_Temperature ",
                "value": "84.923",
                "name": " Garage ",
                "unit": " °F ",
                "measured_at": "2026-09-02T23:16:59+00:00",
            },
            "2026-09-02T23:16:59+00:00",
            SensorSample(entity_id="sensor.garage_temperature", name="Garage", unit="°F", value=84.92, measured_at=instant),
        ),
        (
            {"entity_id": "sensor.freezer_temperature", "value": 0},
            "",
            SensorSample(
                entity_id="sensor.freezer_temperature",
                name="sensor.freezer_temperature",
                unit="",
                value=0.0,
                measured_at=instant,
            ),
        ),
    ]
    for data, exp_text, expected in tests:
        parse_instant.side_effect = [instant]
        result = tested._parse_sample(data)
        assert result == expected
        assert parse_instant.mock_calls == [call(exp_text)]
        assert database.mock_calls == []
        reset_mocks()


@patch("usage.commands.sensor_command.datetime", wraps=datetime)
def test__parse_instant(mock_datetime: MagicMock) -> None:
    def reset_mocks() -> None:
        mock_datetime.reset_mock()

    tested = SensorCommand
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)

    # blank: now
    mock_datetime.now.side_effect = [now]
    result = tested._parse_instant("  ")
    expected = now
    assert result == expected
    assert mock_datetime.mock_calls == [call.now(UTC)]
    reset_mocks()

    # not a date
    with pytest.raises(AppException) as exc_info:
        tested._parse_instant("yesterday")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The instant yesterday is not an ISO 8601 date and time."
    assert mock_datetime.mock_calls == [call.fromisoformat("yesterday")]
    reset_mocks()

    # aware and naive instants
    tests = [
        ("2026-09-02T23:16:59+00:00", datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC)),
        (" 2026-09-02T16:16:59-07:00 ", datetime(2026, 9, 2, 16, 16, 59, tzinfo=timezone(timedelta(hours=-7)))),
        ("2026-09-02T23:16:59", datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC)),
    ]
    for text, expected in tests:
        result = tested._parse_instant(text)
        assert result == expected
        assert mock_datetime.mock_calls == [call.fromisoformat(text.strip())]
        reset_mocks()


@patch.object(SensorCommand, "_hash")
def test__house_from_token(hash_method: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        hash_method.reset_mock()
        database.reset_mock()

    exp_query = "SELECT id FROM houses WHERE ingest_token_hash = %s AND ingest_token_hash <> ''"

    # no token
    for authorization in ["", "  ", "Bearer", "bearer  "]:
        with pytest.raises(AppException) as exc_info:
            tested._house_from_token(authorization)
        assert exc_info.value.status_code == 401
        assert exc_info.value.message == "A sensor token is required."
        assert hash_method.mock_calls == []
        assert database.mock_calls == []
        reset_mocks()

    # unknown token
    hash_method.side_effect = ["the-hash"]
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._house_from_token("Bearer the-token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "The sensor token is not valid."
    assert hash_method.mock_calls == [call("the-token")]
    assert database.mock_calls == [call.fetch_one(exp_query, ("the-hash",))]
    reset_mocks()

    # known token, with or without the scheme
    for authorization in ["Bearer the-token", "bearer  the-token ", " the-token"]:
        hash_method.side_effect = ["the-hash"]
        database.fetch_one.side_effect = [{"id": 3}]
        result = tested._house_from_token(authorization)
        expected = 3
        assert result == expected
        assert hash_method.mock_calls == [call("the-token")]
        assert database.mock_calls == [call.fetch_one(exp_query, ("the-hash",))]
        reset_mocks()


def test__hash() -> None:
    tested = SensorCommand
    result = tested._hash("the-token")
    expected = "c2a73fcf61dfbdcadc79a10ba330b2ef5eb66fc0a6735ed69b796bb3c97b97ae"
    assert result == expected


def test__visible_house_ids() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.fetch_all.side_effect = [[{"house_id": 3}, {"house_id": 5}]]
    result = tested._visible_house_ids(helper_user())
    expected = [3, 5]
    assert result == expected
    exp_calls = [call.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (7,))]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(SensorCommand, "_visible_house_ids")
def test__require_house(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()

    # not linked
    database.fetch_one.side_effect = [{"id": 3}]
    visible_house_ids.side_effect = [[5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 3)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()

    # linked
    database.fetch_one.side_effect = [{"id": 3}]
    visible_house_ids.side_effect = [[3, 5]]
    result = tested._require_house(user, 3)
    assert result is None
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()


@patch.object(SensorCommand, "_visible_house_ids")
def test__require_sensor(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()

    # unknown sensor
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_sensor(user, 9)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The sensor was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [call.fetch_one("SELECT id, house_id FROM sensors WHERE id = %s", (9,))]
    reset_mocks()

    # not linked
    database.fetch_one.side_effect = [{"id": 9, "house_id": 3}]
    visible_house_ids.side_effect = [[5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_sensor(user, 9)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one("SELECT id, house_id FROM sensors WHERE id = %s", (9,))]
    reset_mocks()

    # linked
    database.fetch_one.side_effect = [{"id": 9, "house_id": 3}]
    visible_house_ids.side_effect = [[3, 5]]
    result = tested._require_sensor(user, 9)
    expected = {"id": 9, "house_id": 3}
    assert result == expected
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one("SELECT id, house_id FROM sensors WHERE id = %s", (9,))]
    reset_mocks()
