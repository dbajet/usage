from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.sensor_command import SensorCommand
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample
from usage.structures.sensor_breach import SensorBreach
from usage.structures.session_user import SessionUser
from usage.structures.settings import Settings


def helper_settings(base_url: str = "https://usage.example.com") -> Settings:
    return Settings(
        database_url="postgresql://tests",
        encryption_key="the-key",
        dev_auth_links=False,
        cookie_secure=True,
        base_url=base_url,
        smtp_host="smtp.example",
        smtp_port=587,
        smtp_username="the-username",
        smtp_password="the-password",
        smtp_sender="sender@example.com",
        anthropic_api_key="the-anthropic-key",
        anthropic_model="claude-opus-5",
    )


def helper_instance() -> SensorCommand:
    return SensorCommand(MagicMock(), helper_settings(), MagicMock())


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
    email_sender = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()
        email_sender.reset_mock()

    settings = helper_settings()
    tested = SensorCommand(database, settings, email_sender)
    assert tested._database is database
    assert tested._settings == settings
    assert tested._email_sender is email_sender
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    reset_mocks()


@patch.object(SensorCommand, "_alert")
@patch.object(SensorCommand, "_mark_push")
@patch.object(SensorCommand, "_store_batteries")
@patch.object(SensorCommand, "_find_or_create_sensor")
@patch.object(SensorCommand, "_parse_sample")
@patch("usage.commands.sensor_command.IngestToken")
def test_ingest(
    token_class: MagicMock,
    parse_sample: MagicMock,
    find_or_create_sensor: MagicMock,
    store_batteries: MagicMock,
    mark_push: MagicMock,
    alert: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        token_class.reset_mock()
        parse_sample.reset_mock()
        find_or_create_sensor.reset_mock()
        store_batteries.reset_mock()
        mark_push.reset_mock()
        alert.reset_mock()
        database.reset_mock()

    exp_upsert = """
                    INSERT INTO samples(sensor_id, measured_at, value) VALUES (%s, %s, %s)
                    ON CONFLICT (sensor_id, measured_at) DO UPDATE SET value = EXCLUDED.value
                    """

    # too many samples
    token_class.return_value.house_id.side_effect = [3]
    with pytest.raises(AppException) as exc_info:
        tested.ingest("Bearer the-token", {"samples": [{"entity_id": "sensor.x", "value": 1}] * 1001})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "At most 1000 samples per request."
    assert token_class.mock_calls == [call(database), call().house_id("Bearer the-token")]
    assert parse_sample.mock_calls == []
    assert find_or_create_sensor.mock_calls == []
    assert store_batteries.mock_calls == []
    assert mark_push.mock_calls == []
    assert alert.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # empty batch
    token_class.return_value.house_id.side_effect = [3]
    store_batteries.side_effect = [None]
    alert.side_effect = [None]
    result = tested.ingest("Bearer the-token", {})
    expected = {"accepted": 0, "created": 0}
    assert result == expected
    assert token_class.mock_calls == [call(database), call().house_id("Bearer the-token")]
    assert parse_sample.mock_calls == []
    assert find_or_create_sensor.mock_calls == []
    assert store_batteries.mock_calls == [call([], {})]
    assert mark_push.mock_calls == [call(3)]
    assert alert.mock_calls == [call(3, [], {})]
    exp_calls = [call.transaction(), call.transaction().__enter__(), call.transaction().__exit__(None, None, None)]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # two sensors, one of them new and sent twice: looked up once
    garage = helper_sample()
    garage_later = helper_sample(value=85.1)
    freezer = helper_sample(entity_id="sensor.freezer_temperature", value=-0.58)
    raw = [{"entity_id": "garage"}, {"entity_id": "freezer"}, {"entity_id": "garage-later"}]
    token_class.return_value.house_id.side_effect = [3]
    parse_sample.side_effect = [garage, freezer, garage_later]
    find_or_create_sensor.side_effect = [(9, False), (10, True)]
    store_batteries.side_effect = [None]
    alert.side_effect = [None]
    database.execute.side_effect = [0, 0, 0]
    result = tested.ingest("Bearer the-token", {"samples": raw})
    expected = {"accepted": 3, "created": 1}
    assert result == expected
    assert token_class.mock_calls == [call(database), call().house_id("Bearer the-token")]
    assert parse_sample.mock_calls == [call(raw[0]), call(raw[1]), call(raw[2])]
    assert find_or_create_sensor.mock_calls == [call(3, garage), call(3, freezer)]
    exp_known = {"sensor.garage_temperature": 9, "sensor.freezer_temperature": 10}
    assert store_batteries.mock_calls == [call([garage, freezer, garage_later], exp_known)]
    assert mark_push.mock_calls == [call(3)]
    assert alert.mock_calls == [call(3, [garage, freezer, garage_later], exp_known)]
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


@patch("usage.commands.sensor_command.IngestToken")
@patch("usage.commands.sensor_command.secrets")
def test_issue_token(secrets: MagicMock, token_class: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        secrets.reset_mock()
        token_class.reset_mock()
        database.reset_mock()

    # not an admin
    with pytest.raises(AppException) as exc_info:
        tested.issue_token(helper_user(), 3)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Only admins can do this."
    assert secrets.mock_calls == []
    assert token_class.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.issue_token(helper_user(is_admin=True), 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert secrets.mock_calls == []
    assert token_class.mock_calls == []
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()

    # happy path: the token is returned once, only its hash is stored
    database.fetch_one.side_effect = [{"id": 3}]
    database.execute.side_effect = [0]
    secrets.token_urlsafe.side_effect = ["the-token"]
    token_class.hashed.side_effect = ["the-hash"]
    result = tested.issue_token(helper_user(is_admin=True), 3)
    expected = {"token": "the-token"}
    assert result == expected
    assert secrets.mock_calls == [call.token_urlsafe(32)]
    assert token_class.mock_calls == [call.hashed("the-token")]
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
        {"id": 9, "entity_id": "sealedGarage", "name": "sealedGarageName", "unit": "°F", "color": "#2a78d6", "position": 0, "active": True},
        {"id": 10, "entity_id": "sealedFreezer", "name": "sealedFreezerName", "unit": "°F", "color": "", "position": 1, "active": False},
    ]
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [latest, sensor_rows]
    database.decrypt_rows.side_effect = [
        [
            {
                "id": 9,
                "entity_id": "sensor.garage_temperature",
                "name": "Garage",
                "unit": "°F",
                "color": "#2a78d6",
                "position": 0,
                "active": True,
                "threshold_min": Decimal("40.00"),
                "threshold_max": Decimal("85.00"),
                "battery": 87,
                "battery_at": datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC),
            },
            {
                "id": 10,
                "entity_id": "sensor.freezer_temperature",
                "name": "Freezer",
                "unit": "°F",
                "color": "",
                "position": 1,
                "active": False,
                "threshold_min": None,
                "threshold_max": None,
                "battery": None,
                "battery_at": None,
            },
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
                "color": "#2a78d6",
                "position": 0,
                "active": True,
                "last_value": 84.9,
                "last_at": "2026-09-02T23:16:59+00:00",
                "threshold_min": 40.0,
                "threshold_max": 85.0,
                "battery": 87,
                "battery_at": "2026-09-02T23:16:59+00:00",
            },
            {
                "id": 10,
                "entity_id": "sensor.freezer_temperature",
                "name": "Freezer",
                "unit": "°F",
                "color": "",
                "position": 1,
                "active": False,
                "last_value": None,
                "last_at": "",
                "threshold_min": None,
                "threshold_max": None,
                "battery": None,
                "battery_at": "",
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
                SELECT id, entity_id_sealed AS entity_id, name_sealed AS name, unit, color, position, active,
                       threshold_min, threshold_max, battery, battery_at
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

    # the colour must be a hex triplet
    require_sensor.side_effect = [{"id": 9, "house_id": 3}]
    with pytest.raises(AppException) as exc_info:
        tested.update_sensor(user, 9, {"name": "Garage", "unit": "°F", "color": "blue", "active": True})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The colour must be like #2a78d6, or empty for the default."
    assert require_sensor.mock_calls == [call(user, 9)]
    assert database.mock_calls == []
    reset_mocks()

    # the alert range must be the right way round
    require_sensor.side_effect = [{"id": 9, "house_id": 3}]
    with pytest.raises(AppException) as exc_info:
        tested.update_sensor(user, 9, {"name": "Garage", "unit": "°F", "active": True, "threshold_min": 85, "threshold_max": 40})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The alert minimum must be lower than the maximum."
    assert require_sensor.mock_calls == [call(user, 9)]
    assert database.mock_calls == []
    reset_mocks()

    exp_update = """
            UPDATE sensors
            SET name_sealed = %s, unit = %s, color = %s, active = %s, threshold_min = %s, threshold_max = %s,
                alert_state = CASE
                    WHEN threshold_min IS DISTINCT FROM %s OR threshold_max IS DISTINCT FROM %s THEN %s
                    ELSE alert_state END
            WHERE id = %s
            """

    # happy paths: a colour, or the default
    tests = [(" #2A78D6 ", "#2a78d6"), ("", "")]
    for color, exp_color in tests:
        require_sensor.side_effect = [{"id": 9, "house_id": 3}]
        database.encrypt.side_effect = ["sealedGarage"]
        database.execute.side_effect = [0]
        data = {"name": " Garage ", "unit": " °C ", "color": color, "active": False, "threshold_min": "4.567", "threshold_max": 30}
        result = tested.update_sensor(user, 9, data)
        expected = {"message": "Sensor updated."}
        assert result == expected
        assert require_sensor.mock_calls == [call(user, 9)]
        exp_calls = [
            call.encrypt("Garage"),
            call.execute(exp_update, ("sealedGarage", "°C", exp_color, False, 4.57, 30.0, 4.57, 30.0, "", 9)),
        ]
        assert database.mock_calls == exp_calls
        reset_mocks()

    # no bound on either side
    require_sensor.side_effect = [{"id": 9, "house_id": 3}]
    database.encrypt.side_effect = ["sealedGarage"]
    database.execute.side_effect = [0]
    result = tested.update_sensor(user, 9, {"name": "Garage", "unit": "°F", "color": "", "active": True})
    expected = {"message": "Sensor updated."}
    assert result == expected
    assert require_sensor.mock_calls == [call(user, 9)]
    exp_calls = [
        call.encrypt("Garage"),
        call.execute(exp_update, ("sealedGarage", "°F", "", True, None, None, None, None, "", 9)),
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


@patch("usage.commands.sensor_command.SeriesPulse")
@patch("usage.commands.sensor_command.datetime", wraps=datetime)
@patch.object(SensorCommand, "_due")
@patch.object(SensorCommand, "_latest")
@patch.object(SensorCommand, "_require_house")
def test_series(
    require_house: MagicMock,
    latest: MagicMock,
    due: MagicMock,
    mock_datetime: MagicMock,
    pulse: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        latest.reset_mock()
        due.reset_mock()
        mock_datetime.reset_mock()
        pulse.reset_mock()
        database.reset_mock()

    user = helper_user()
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)

    # unknown range
    require_house.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.series(user, 3, 14, False, 0)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The range must be one of 1, 7, 30, 365 days."
    assert require_house.mock_calls == [call(user, 3)]
    assert latest.mock_calls == []
    assert due.mock_calls == []
    assert mock_datetime.mock_calls == []
    assert pulse.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # negative offset
    require_house.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.series(user, 3, 7, False, -1)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The offset counts periods back from now."
    assert require_house.mock_calls == [call(user, 3)]
    assert latest.mock_calls == []
    assert due.mock_calls == []
    assert mock_datetime.mock_calls == []
    assert pulse.mock_calls == []
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
    tests = [
        (False, 0, "2026-08-27T12:00:00+00:00", "2026-09-03T12:00:00+00:00"),
        (True, 0, "2026-08-20T12:00:00+00:00", "2026-09-03T12:00:00+00:00"),
        (False, 2, "2026-08-13T12:00:00+00:00", "2026-08-20T12:00:00+00:00"),
    ]
    exp_latest = [{"sensor_id": 9, "value": 84.9, "at": "2026-09-03T11:50:00+00:00", "battery": 74, "battery_at": ""}]
    for previous, offset, exp_since, exp_until in tests:
        require_house.side_effect = [None]
        latest.side_effect = [exp_latest]
        due.side_effect = [datetime(2026, 9, 3, 12, 9, 59, tzinfo=UTC)]
        mock_datetime.now.side_effect = [now]
        pulse.stamp.side_effect = ["theStamp"]
        pulse.next_poll.side_effect = [599]
        database.fetch_all.side_effect = [sensor_rows, rows]
        database.decrypt_rows.side_effect = [[{"id": 9, "name": "Garage", "unit": "°F"}, {"id": 10, "name": "Freezer", "unit": "°F"}]]
        result = tested.series(user, 3, 7, previous, offset)
        expected = {
            "days": 7,
            "bucket_minutes": 60,
            "previous": previous,
            "offset": offset,
            "until": exp_until,
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
            "latest": exp_latest,
            "stamp": "theStamp",
            "next_poll_seconds": 599,
        }
        assert result == expected
        assert require_house.mock_calls == [call(user, 3)]
        exp_series = expected["series"]
        assert latest.mock_calls == [call(3, [{"id": 9, "name": "Garage", "unit": "°F"}, {"id": 10, "name": "Freezer", "unit": "°F"}])]
        assert due.mock_calls == [call(3)]
        assert mock_datetime.mock_calls == [call.now(UTC)]
        assert pulse.mock_calls == [
            call.stamp(exp_series, exp_latest),
            call.next_poll([datetime(2026, 9, 3, 12, 9, 59, tzinfo=UTC)], now),
        ]
        exp_calls = [
            call.fetch_all(
                """
                SELECT id, name_sealed AS name, unit, battery, battery_at
                FROM sensors WHERE house_id = %s AND active ORDER BY position, id
                """,
                (3,),
            ),
            call.decrypt_rows(sensor_rows, ("name",)),
            call.fetch_all(
                """
            SELECT samples.sensor_id,
                   date_bin(%s, samples.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   AVG(samples.value) AS average, MIN(samples.value) AS low, MAX(samples.value) AS high
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s AND sensors.active AND samples.measured_at >= %s AND samples.measured_at < %s
            GROUP BY samples.sensor_id, bucket
            ORDER BY samples.sensor_id, bucket
            """,
                (timedelta(minutes=60), 3, exp_since, exp_until),
            ),
        ]
        assert database.mock_calls == exp_calls
        reset_mocks()


@patch.object(SensorCommand, "_require_house")
def test_alerts(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_fetch = call.fetch_one(
        "SELECT enabled FROM sensor_alerts WHERE user_id = %s AND house_id = %s",
        (7, 3),
    )

    # never asked, asked and on, asked and off
    tests: list[tuple[dict[str, bool] | None, bool]] = [(None, False), ({"enabled": True}, True), ({"enabled": False}, False)]
    for row, exp_enabled in tests:
        require_house.side_effect = [None]
        database.fetch_one.side_effect = [row]
        result = tested.alerts(user, 3)
        expected = {"enabled": exp_enabled}
        assert result == expected
        assert require_house.mock_calls == [call(user, 3)]
        assert database.mock_calls == [exp_fetch]
        reset_mocks()


@patch.object(SensorCommand, "_require_house")
def test_set_alerts(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_upsert = """
            INSERT INTO sensor_alerts(user_id, house_id, enabled) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, house_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """

    tests = [
        ({"house_id": 3, "enabled": True}, True, "Threshold alerts enabled for this house."),
        ({"house_id": "3", "enabled": False}, False, "Threshold alerts disabled for this house."),
        ({}, False, "Threshold alerts disabled for this house."),
    ]
    for data, exp_enabled, exp_message in tests:
        house_id = int(data.get("house_id") or 0)
        require_house.side_effect = [None]
        database.execute.side_effect = [0]
        result = tested.set_alerts(user, data)
        expected = {"message": exp_message}
        assert result == expected
        assert require_house.mock_calls == [call(user, house_id)]
        assert database.mock_calls == [call.execute(exp_upsert, (7, house_id, exp_enabled))]
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


def test__mark_push() -> None:
    tested = helper_instance()
    database = tested._database
    exp_sql = """
            UPDATE houses
            SET sensors_push_seconds = CASE
                    WHEN sensors_pushed_at IS NULL THEN sensors_push_seconds
                    ELSE LEAST(%s, GREATEST(1, EXTRACT(EPOCH FROM (now() - sensors_pushed_at))::int))
                END,
                sensors_pushed_at = now()
            WHERE id = %s
            """

    database.execute.side_effect = [None]
    result = tested._mark_push(3)
    assert result is None
    # the ceiling travels with the statement: an outage is not a cadence
    assert database.mock_calls == [call.execute(exp_sql, (1800, 3))]


@patch("usage.commands.sensor_command.datetime", wraps=datetime)
def test__due(mock_datetime: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        mock_datetime.reset_mock()
        database.reset_mock()

    exp_sql = "SELECT sensors_pushed_at, sensors_push_seconds FROM houses WHERE id = %s"
    pushed = datetime(2026, 9, 3, 11, 50, tzinfo=UTC)

    # two pushes seen: the gap between them is what the page is told to wait
    database.fetch_one.side_effect = [{"sensors_pushed_at": pushed, "sensors_push_seconds": 599}]
    result = tested._due(3)
    assert result == datetime(2026, 9, 3, 11, 59, 59, tzinfo=UTC)
    assert database.mock_calls == [call.fetch_one(exp_sql, (3,))]
    reset_mocks()

    # only one so far: the assumed cadence, counted from when it landed
    database.fetch_one.side_effect = [{"sensors_pushed_at": pushed, "sensors_push_seconds": None}]
    result = tested._due(3)
    assert result == datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    assert database.mock_calls == [call.fetch_one(exp_sql, (3,))]
    reset_mocks()

    # a house that has never pushed, and one that is not there at all: nothing
    # to go on either way, and the caller answers that with the ceiling
    for row in [{"sensors_pushed_at": None, "sensors_push_seconds": 60}, None]:
        database.fetch_one.side_effect = [row]
        result = tested._due(3)
        assert result is None
        assert database.mock_calls == [call.fetch_one(exp_sql, (3,))]
        reset_mocks()


def test__latest() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_sql = """
            SELECT DISTINCT ON (samples.sensor_id) samples.sensor_id, samples.measured_at, samples.value
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s AND sensors.active
            ORDER BY samples.sensor_id, samples.measured_at DESC
            """
    rows = [
        {"sensor_id": 9, "measured_at": datetime(2026, 9, 3, 11, 50, tzinfo=UTC), "value": Decimal("84.90")},
        {"sensor_id": 10, "measured_at": datetime(2026, 9, 3, 11, 40, tzinfo=UTC), "value": Decimal("-17.20")},
    ]
    sensors = [
        {"id": 9, "battery": 74, "battery_at": datetime(2026, 9, 3, 11, 50, tzinfo=UTC)},
        {"id": 10, "battery": None, "battery_at": None},
        # a sensor quiet since it was created still has a tile, but nothing to put on it
        {"id": 11, "battery": 12, "battery_at": None},
    ]

    database.fetch_all.side_effect = [rows]
    result = tested._latest(3, sensors)
    expected = [
        {
            "sensor_id": 9,
            "value": 84.9,
            "at": "2026-09-03T11:50:00+00:00",
            "battery": 74,
            "battery_at": "2026-09-03T11:50:00+00:00",
        },
        {"sensor_id": 10, "value": -17.2, "at": "2026-09-03T11:40:00+00:00", "battery": None, "battery_at": ""},
    ]
    assert result == expected
    assert database.mock_calls == [call.fetch_all(exp_sql, (3,))]
    reset_mocks()

    # a house whose thermometers have never reported
    database.fetch_all.side_effect = [[]]
    result = tested._latest(3, sensors)
    assert result == []
    assert database.mock_calls == [call.fetch_all(exp_sql, (3,))]
    reset_mocks()


def test__store_batteries() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    def helper_charged(entity_id: str, battery: int | None, minute: int) -> SensorSample:
        return SensorSample(
            entity_id=entity_id,
            name="Garage",
            unit="°F",
            value=84.9,
            measured_at=datetime(2026, 9, 2, 23, minute, 0, tzinfo=UTC),
            battery=battery,
        )

    known = {"sensor.garage_temperature": 9, "sensor.freezer_temperature": 10}

    # nothing carries a charge: nothing is written
    result = tested._store_batteries([helper_charged("sensor.garage_temperature", None, 10)], known)
    assert result is None
    assert database.mock_calls == []
    reset_mocks()

    # the newest charge of each thermometer wins, whatever order they arrive in,
    # and a sample of an entity that is not in the push is ignored
    samples = [
        helper_charged("sensor.garage_temperature", 90, 20),
        helper_charged("sensor.garage_temperature", 88, 40),
        helper_charged("sensor.garage_temperature", 89, 30),
        helper_charged("sensor.freezer_temperature", 12, 20),
        helper_charged("sensor.freezer_temperature", None, 50),
        helper_charged("sensor.unknown_temperature", 77, 20),
    ]
    database.execute.side_effect = [0, 0]
    result = tested._store_batteries(samples, known)
    assert result is None
    exp_calls = [
        call.execute("UPDATE sensors SET battery = %s, battery_at = %s WHERE id = %s", (88, "2026-09-02T23:40:00+00:00", 9)),
        call.execute("UPDATE sensors SET battery = %s, battery_at = %s WHERE id = %s", (12, "2026-09-02T23:20:00+00:00", 10)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(SensorCommand, "_parse_battery")
@patch.object(SensorCommand, "_parse_instant")
def test__parse_sample(parse_instant: MagicMock, parse_battery: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        parse_instant.reset_mock()
        parse_battery.reset_mock()
        database.reset_mock()

    instant = datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC)

    # missing entity
    with pytest.raises(AppException) as exc_info:
        tested._parse_sample({"value": 84.9})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Each sample needs an entity_id."
    assert parse_instant.mock_calls == []
    assert parse_battery.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # values that are not numbers
    for value in ["hot", float("nan"), float("inf")]:
        with pytest.raises(AppException) as exc_info:
            tested._parse_sample({"entity_id": "sensor.garage_temperature", "value": value})
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The value of sensor.garage_temperature is not a number."
        assert parse_instant.mock_calls == []
        assert parse_battery.mock_calls == []
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
                "battery": 87,
            },
            "2026-09-02T23:16:59+00:00",
            87,
            SensorSample(
                entity_id="sensor.garage_temperature",
                name="Garage",
                unit="°F",
                value=84.92,
                measured_at=instant,
                battery=87,
            ),
        ),
        (
            {"entity_id": "sensor.freezer_temperature", "value": 0},
            "",
            None,
            SensorSample(
                entity_id="sensor.freezer_temperature",
                name="sensor.freezer_temperature",
                unit="",
                value=0.0,
                measured_at=instant,
                battery=None,
            ),
        ),
    ]
    for data, exp_text, charge, expected in tests:
        parse_instant.side_effect = [instant]
        parse_battery.side_effect = [charge]
        result = tested._parse_sample(data)
        assert result == expected
        assert parse_instant.mock_calls == [call(exp_text)]
        assert parse_battery.mock_calls == [call(data.get("battery"), expected.entity_id)]
        assert database.mock_calls == []
        reset_mocks()


def test__parse_battery() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # a thermometer on mains power sends none; a charge is a whole percentage
    tests: list[tuple[Any, int | None]] = [
        (None, None),
        ("", None),
        ("   ", None),
        (87, 87),
        ("87", 87),
        (12.6, 13),
        (0, 0),
        (100, 100),
    ]
    for raw, expected in tests:
        result = tested._parse_battery(raw, "sensor.garage_temperature")
        assert result == expected
        assert database.mock_calls == []
        reset_mocks()

    # not a number at all
    for raw in ["full", [1]]:
        with pytest.raises(AppException) as exc_info:
            tested._parse_battery(raw, "sensor.garage_temperature")
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The battery of sensor.garage_temperature is not a number."
        assert database.mock_calls == []
        reset_mocks()

    # a number, but not a percentage
    for raw in [-1, 101]:
        with pytest.raises(AppException) as exc_info:
            tested._parse_battery(raw, "sensor.garage_temperature")
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The battery of sensor.garage_temperature is not a percentage."
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


def test__threshold() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    tests: list[tuple[dict[str, Any], float | None]] = [
        ({}, None),
        ({"threshold_min": None}, None),
        ({"threshold_min": ""}, None),
        ({"threshold_min": "   "}, None),
        ({"threshold_min": 30}, 30.0),
        ({"threshold_min": "4.567"}, 4.57),
        ({"threshold_min": -12.344}, -12.34),
    ]
    for data, expected in tests:
        result = tested._threshold(data, "threshold_min")
        assert result == expected
        assert database.mock_calls == []
        reset_mocks()

    # anything that is not a number is refused
    for value in ["twenty", [1]]:
        with pytest.raises(AppException) as exc_info:
            tested._threshold({"threshold_min": value}, "threshold_min")
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The alert minimum and maximum must be numbers."
        assert database.mock_calls == []
        reset_mocks()


@patch.object(SensorCommand, "_send_alerts")
@patch.object(SensorCommand, "_breaches")
def test__alert(breaches: MagicMock, send_alerts: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        breaches.reset_mock()
        send_alerts.reset_mock()
        database.reset_mock()

    garage = helper_sample()
    known = {"sensor.garage_temperature": 9}

    # nothing crossed: no email
    breaches.side_effect = [[]]
    result = tested._alert(3, [garage], known)
    assert result is None
    assert breaches.mock_calls == [call([garage], known)]
    assert send_alerts.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # a crossing: the house is told
    breach = SensorBreach(sensor_id=9, name="Garage", value=91.0, unit="°F", state="above", threshold=85.0)
    breaches.side_effect = [[breach]]
    send_alerts.side_effect = [None]
    result = tested._alert(3, [garage], known)
    assert result is None
    assert breaches.mock_calls == [call([garage], known)]
    assert send_alerts.mock_calls == [call(3, [breach])]
    assert database.mock_calls == []
    reset_mocks()


@patch.object(SensorCommand, "_state_of")
@patch.object(SensorCommand, "_last_sample")
def test__breaches(last_sample: MagicMock, state_of: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        last_sample.reset_mock()
        state_of.reset_mock()
        database.reset_mock()

    garage = helper_sample()
    freezer = helper_sample(entity_id="sensor.freezer_temperature", value=-0.58)
    known = {"sensor.garage_temperature": 9, "sensor.freezer_temperature": 10}
    exp_fetch = call.fetch_all(
        """
                SELECT id, name_sealed AS name, unit, threshold_min, threshold_max, alert_state
                FROM sensors
                WHERE id = ANY(%s) AND (threshold_min IS NOT NULL OR threshold_max IS NOT NULL)
                ORDER BY position, id
                """,
        ([9, 10],),
    )

    # no sensor in the push: nothing is even looked up
    result = tested._breaches([], {})
    assert result == []
    assert last_sample.mock_calls == []
    assert state_of.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # no sensor carries a range
    sealed: list[dict[str, Any]] = []
    database.fetch_all.side_effect = [sealed]
    database.decrypt_rows.side_effect = [[]]
    result = tested._breaches([garage, freezer], known)
    assert result == []
    assert last_sample.mock_calls == []
    assert state_of.mock_calls == []
    assert database.mock_calls == [exp_fetch, call.decrypt_rows(sealed, ("name",))]
    reset_mocks()

    # one sensor just went out of range, one was already out, one has no sample
    # in this push, and one came back to normal: only the crossing is reported,
    # and only the sensors whose state moved are written back.
    sealed = [{"id": 9}, {"id": 10}, {"id": 11}, {"id": 12}]
    rows = [
        {"id": 9, "name": "Garage", "unit": "°F", "threshold_min": None, "threshold_max": Decimal("85.00"), "alert_state": ""},
        {"id": 10, "name": "Freezer", "unit": "°F", "threshold_min": Decimal("0.00"), "threshold_max": None, "alert_state": "below"},
        {"id": 11, "name": "Cave", "unit": "°F", "threshold_min": Decimal("40.00"), "threshold_max": None, "alert_state": ""},
        {"id": 12, "name": "Grenier", "unit": "°F", "threshold_min": Decimal("40.00"), "threshold_max": None, "alert_state": "below"},
    ]
    database.fetch_all.side_effect = [sealed]
    database.decrypt_rows.side_effect = [rows]
    last_sample.side_effect = [garage, freezer, None, garage]
    state_of.side_effect = [("above", 85.0), ("below", 0.0), ("", 0.0)]
    database.execute.side_effect = [0, 0]
    result = tested._breaches([garage, freezer], known)
    expected = [SensorBreach(sensor_id=9, name="Garage", value=84.9, unit="°F", state="above", threshold=85.0)]
    assert result == expected
    exp_calls = [
        call(9, [garage, freezer], known),
        call(10, [garage, freezer], known),
        call(11, [garage, freezer], known),
        call(12, [garage, freezer], known),
    ]
    assert last_sample.mock_calls == exp_calls
    assert state_of.mock_calls == [call(84.9, rows[0]), call(-0.58, rows[1]), call(84.9, rows[3])]
    exp_calls = [
        exp_fetch,
        call.decrypt_rows(sealed, ("name",)),
        call.execute("UPDATE sensors SET alert_state = %s WHERE id = %s", ("above", 9)),
        call.execute("UPDATE sensors SET alert_state = %s WHERE id = %s", ("", 12)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__last_sample() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    early = helper_sample(value=84.9)
    late = SensorSample(
        entity_id="sensor.garage_temperature",
        name="Garage",
        unit="°F",
        value=85.1,
        measured_at=datetime(2026, 9, 2, 23, 26, 59, tzinfo=UTC),
    )
    freezer = helper_sample(entity_id="sensor.freezer_temperature", value=-0.58)
    known = {"sensor.garage_temperature": 9, "sensor.freezer_temperature": 10}

    tests: list[tuple[int, SensorSample | None]] = [(9, late), (10, freezer), (11, None)]
    for sensor_id, expected in tests:
        result = tested._last_sample(sensor_id, [early, freezer, late], known)
        assert result == expected
        assert database.mock_calls == []
        reset_mocks()


def test__state_of() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    both = {"threshold_min": Decimal("40.00"), "threshold_max": Decimal("85.00")}
    low_only = {"threshold_min": Decimal("40.00"), "threshold_max": None}
    high_only = {"threshold_min": None, "threshold_max": Decimal("85.00")}
    tests: list[tuple[float, dict[str, Any], tuple[str, float]]] = [
        (39.99, both, ("below", 40.0)),
        (40.0, both, ("", 0.0)),
        (62.5, both, ("", 0.0)),
        (85.0, both, ("", 0.0)),
        (85.01, both, ("above", 85.0)),
        (200.0, low_only, ("", 0.0)),
        (12.0, low_only, ("below", 40.0)),
        (-200.0, high_only, ("", 0.0)),
        (91.0, high_only, ("above", 85.0)),
    ]
    for value, sensor, expected in tests:
        result = tested._state_of(value, sensor)
        assert result == expected
        assert database.mock_calls == []
        reset_mocks()


@patch("usage.commands.sensor_command.logging")
@patch("usage.commands.sensor_command.EmailTexts")
def test__send_alerts(email_texts: MagicMock, mock_logging: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    email_sender = tested._email_sender
    logger = MagicMock()

    def reset_mocks() -> None:
        email_texts.reset_mock()
        mock_logging.reset_mock()
        logger.reset_mock()
        database.reset_mock()
        email_sender.reset_mock()

    breach = SensorBreach(sensor_id=9, name="Garage", value=91.0, unit="°F", state="above", threshold=85.0)
    exp_recipients = call.fetch_all(
        """
            SELECT users.email_sealed AS email
            FROM sensor_alerts
            JOIN users ON users.id = sensor_alerts.user_id
            JOIN user_houses ON user_houses.user_id = sensor_alerts.user_id
                            AND user_houses.house_id = sensor_alerts.house_id
            WHERE sensor_alerts.house_id = %s AND sensor_alerts.enabled
            ORDER BY sensor_alerts.user_id
            """,
        (3,),
    )
    exp_house = call.fetch_one("SELECT name_sealed AS name FROM houses WHERE id = %s", (3,))

    # nobody asked for the alerts: no email, not even the house is read
    database.fetch_all.side_effect = [[]]
    result = tested._send_alerts(3, [breach])
    assert result is None
    assert email_texts.mock_calls == []
    assert mock_logging.mock_calls == []
    assert logger.mock_calls == []
    assert database.mock_calls == [exp_recipients]
    assert email_sender.mock_calls == []
    reset_mocks()

    # two subscribers, the second one's email fails and is logged
    database.fetch_all.side_effect = [[{"email": "sealedJane"}, {"email": "sealedJohn"}]]
    database.fetch_one.side_effect = [{"name": "sealedFremur"}]
    database.decrypt.side_effect = ["Fremur", "jane@example.com", "john@example.com"]
    email_texts.sensor_alert.side_effect = [("the subject", ["the body"])]
    email_sender.send.side_effect = [True, False]
    mock_logging.getLogger.side_effect = [logger]
    result = tested._send_alerts(3, [breach])
    assert result is None
    assert email_texts.mock_calls == [call.sensor_alert("Fremur", [breach], "https://usage.example.com")]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    exp_calls = [call.warning("[ALERT] email failed for %s of house %s", "john@example.com", 3)]
    assert logger.mock_calls == exp_calls
    exp_calls = [
        exp_recipients,
        exp_house,
        call.decrypt("sealedFremur"),
        call.decrypt("sealedJane"),
        call.decrypt("sealedJohn"),
    ]
    assert database.mock_calls == exp_calls
    exp_calls = [
        call.send("jane@example.com", "the subject", ["the body"]),
        call.send("john@example.com", "the subject", ["the body"]),
    ]
    assert email_sender.mock_calls == exp_calls
    reset_mocks()

    # the house vanished between the push and the email: it goes out unnamed
    database.fetch_all.side_effect = [[{"email": "sealedJane"}]]
    database.fetch_one.side_effect = [None]
    database.decrypt.side_effect = ["jane@example.com"]
    email_texts.sensor_alert.side_effect = [("the subject", ["the body"])]
    email_sender.send.side_effect = [True]
    result = tested._send_alerts(3, [breach])
    assert result is None
    assert email_texts.mock_calls == [call.sensor_alert("", [breach], "https://usage.example.com")]
    assert mock_logging.mock_calls == []
    assert logger.mock_calls == []
    assert database.mock_calls == [exp_recipients, exp_house, call.decrypt("sealedJane")]
    assert email_sender.mock_calls == [call.send("jane@example.com", "the subject", ["the body"])]
    reset_mocks()
