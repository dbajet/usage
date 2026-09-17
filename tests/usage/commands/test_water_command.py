from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.water_command import WaterCommand
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser
from usage.structures.water_meter import WaterMeter

SQL_FEEDS = """
                SELECT id, hostname, username_sealed AS username, meter_uuid_sealed AS meter_uuid, export_unit,
                       active, last_sync_at, last_point_at, last_error, backfill_from, backfill_done, daily_max
                FROM water_feeds WHERE house_id = %s ORDER BY id
                """
SQL_COUNTS = "SELECT COUNT(*) AS points, MIN(measured_at) AS first_at FROM water_points WHERE feed_id = %s"
SQL_INSERT = """
            INSERT INTO water_feeds(house_id, hostname, username_sealed, username_hash, password_sealed,
                                    meter_uuid_sealed, meter_uuid_hash, export_unit, daily_max)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """
SQL_UPDATE = """
            UPDATE water_feeds
            SET hostname = %s, username_sealed = %s, username_hash = %s, password_sealed = %s,
                meter_uuid_sealed = %s, meter_uuid_hash = %s, export_unit = %s, active = %s,
                daily_max = %s, last_error = '',
                over_daily = CASE WHEN daily_max IS DISTINCT FROM %s THEN false ELSE over_daily END
            WHERE id = %s
            """
SQL_SERIES = """
            SELECT date_bin(%s, water_points.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   SUM(water_points.volume) AS volume
            FROM water_points JOIN water_feeds ON water_feeds.id = water_points.feed_id
            WHERE water_feeds.house_id = %s AND water_feeds.active
              AND water_points.measured_at >= %s AND water_points.measured_at < %s
            GROUP BY bucket ORDER BY bucket
            """
SQL_LATEST = """
            SELECT water_points.measured_at, water_points.volume, water_points.reading
            FROM water_points JOIN water_feeds ON water_feeds.id = water_points.feed_id
            WHERE water_feeds.house_id = %s AND water_feeds.active
            ORDER BY water_points.measured_at DESC LIMIT 1
            """


def helper_instance() -> WaterCommand:
    return WaterCommand(MagicMock())


def helper_user(is_admin: bool = True) -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane", is_admin=is_admin)


def helper_payload() -> dict[str, Any]:
    return {
        "house_id": 3,
        "hostname": "eyeonwater.com",
        "username": "theUsername",
        "password": "thePassword",
        "meter_uuid": "1234567890123456789",
        "export_unit": "Gallons",
        "active": True,
    }


def test___init__() -> None:
    database = MagicMock()
    tested = WaterCommand(database)
    assert tested._database is database


@patch.object(WaterCommand, "_require_house")
@patch.object(WaterCommand, "_require_admin")
def test_list_feeds(require_admin: MagicMock, require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    rows = [{"id": 11, "username": "sealedUsername", "meter_uuid": "sealedUuid"}]
    decrypted = [
        {
            "id": 11,
            "hostname": "eyeonwater.com",
            "username": "theUsername",
            "meter_uuid": "1234567890123456789",
            "export_unit": "Gallons",
            "active": True,
            "last_sync_at": datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
            "last_point_at": datetime(2026, 9, 14, 22, 29, tzinfo=UTC),
            "last_error": "",
            "backfill_from": date(2021, 4, 1),
            "backfill_done": True,
            "daily_max": Decimal("1.5"),
        },
    ]
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [decrypted]
    database.fetch_one.side_effect = [{"points": 175200, "first_at": datetime(2021, 4, 1, 7, 0, tzinfo=UTC)}]
    result = tested.list_feeds(user, 3)
    expected = {
        "feeds": [
            {
                "id": 11,
                "hostname": "eyeonwater.com",
                "username": "theUsername",
                "meter_uuid": "1234567890123456789",
                "export_unit": "Gallons",
                "active": True,
                "last_sync_at": "2026-09-15T09:00:00+00:00",
                "last_point_at": "2026-09-14T22:29:00+00:00",
                "last_error": "",
                "backfill_from": "2021-04-01",
                "backfill_done": True,
                "daily_max": 1.5,
                "points": 175200,
                "first_point_at": "2021-04-01T07:00:00+00:00",
            },
        ],
    }
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.fetch_all(SQL_FEEDS, (3,)),
        call.decrypt_rows(rows, ("username", "meter_uuid")),
        call.fetch_one(SQL_COUNTS, (11,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a feed nothing has been collected for yet
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [
        [
            {
                "id": 11,
                "hostname": "eyeonwater.com",
                "username": "theUsername",
                "meter_uuid": "1234567890123456789",
                "export_unit": "Gallons",
                "active": False,
                "last_sync_at": None,
                "last_point_at": None,
                "last_error": "EyeOnWater could not be reached.",
                "backfill_from": None,
                "backfill_done": False,
                "daily_max": None,
            },
        ],
    ]
    database.fetch_one.side_effect = [None]
    result = tested.list_feeds(user, 3)
    expected = {
        "feeds": [
            {
                "id": 11,
                "hostname": "eyeonwater.com",
                "username": "theUsername",
                "meter_uuid": "1234567890123456789",
                "export_unit": "Gallons",
                "active": False,
                "last_sync_at": "",
                "last_point_at": "",
                "last_error": "EyeOnWater could not be reached.",
                "backfill_from": "",
                "backfill_done": False,
                "daily_max": None,
                "points": 0,
                "first_point_at": "",
            },
        ],
    }
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.water_command.EyeOnWaterClient")
@patch.object(WaterCommand, "_probe")
@patch.object(WaterCommand, "_resolve_meter")
@patch.object(WaterCommand, "_meter_uuid")
@patch.object(WaterCommand, "_hostname")
@patch.object(WaterCommand, "_require_house")
@patch.object(WaterCommand, "_require_admin")
def test_create_feed(
    require_admin: MagicMock,
    require_house: MagicMock,
    hostname: MagicMock,
    meter_uuid: MagicMock,
    resolve_meter: MagicMock,
    probe: MagicMock,
    client_class: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    client = MagicMock()

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_house.reset_mock()
        hostname.reset_mock()
        meter_uuid.reset_mock()
        resolve_meter.reset_mock()
        probe.reset_mock()
        client_class.reset_mock()
        client.reset_mock()
        database.reset_mock()

    user = helper_user()

    # the credentials are mandatory
    for payload in [{**helper_payload(), "username": " "}, {**helper_payload(), "password": ""}]:
        require_admin.side_effect = [None]
        require_house.side_effect = [None]
        hostname.side_effect = ["eyeonwater.com"]
        meter_uuid.side_effect = ["1234567890123456789"]
        with pytest.raises(AppException) as exc_info:
            tested.create_feed(user, payload)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "Enter the EyeOnWater username and password."
        assert require_admin.mock_calls == [call(user)]
        assert require_house.mock_calls == [call(user, 3)]
        assert hostname.mock_calls == [call(payload)]
        assert meter_uuid.mock_calls == [call(payload)]
        assert resolve_meter.mock_calls == []
        assert probe.mock_calls == []
        assert client_class.mock_calls == []
        assert client.mock_calls == []
        assert database.mock_calls == []
        reset_mocks()

    # the meter is already collected
    payload = helper_payload()
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    hostname.side_effect = ["eyeonwater.com"]
    meter_uuid.side_effect = ["1234567890123456789"]
    client_class.side_effect = [client]
    resolve_meter.side_effect = ["1234567890123456789"]
    probe.side_effect = [None]
    database.blind_index.side_effect = ["theUuidHash"]
    database.fetch_one.side_effect = [{"id": 11}]
    with pytest.raises(AppException) as exc_info:
        tested.create_feed(user, payload)
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "This meter is already collected for this house."
    assert client_class.mock_calls == [call("eyeonwater.com", "theUsername", "thePassword", "Gallons")]
    assert resolve_meter.mock_calls == [call(client, "1234567890123456789")]
    assert probe.mock_calls == [call(client, "1234567890123456789")]
    assert client.mock_calls == []
    exp_calls = [
        call.blind_index("1234567890123456789"),
        call.fetch_one("SELECT id FROM water_feeds WHERE house_id = %s AND meter_uuid_hash = %s", (3, "theUuidHash")),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # stored
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    hostname.side_effect = ["eyeonwater.com"]
    meter_uuid.side_effect = ["1234567890123456789"]
    client_class.side_effect = [client]
    resolve_meter.side_effect = ["1234567890123456789"]
    probe.side_effect = [None]
    database.blind_index.side_effect = ["theUuidHash", "theUsernameHash", "theUuidHash"]
    database.encrypt.side_effect = ["sealedUsername", "sealedPassword", "sealedUuid"]
    database.fetch_one.side_effect = [None]
    database.execute.side_effect = [11]
    result = tested.create_feed(user, payload)
    expected = {"id": 11, "message": "Water feed added. The first import starts within a minute."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    assert hostname.mock_calls == [call(payload)]
    assert meter_uuid.mock_calls == [call(payload)]
    assert client_class.mock_calls == [call("eyeonwater.com", "theUsername", "thePassword", "Gallons")]
    assert resolve_meter.mock_calls == [call(client, "1234567890123456789")]
    assert probe.mock_calls == [call(client, "1234567890123456789")]
    assert client.mock_calls == []
    exp_calls = [
        call.blind_index("1234567890123456789"),
        call.fetch_one("SELECT id FROM water_feeds WHERE house_id = %s AND meter_uuid_hash = %s", (3, "theUuidHash")),
        call.encrypt("theUsername"),
        call.blind_index("theUsername"),
        call.encrypt("thePassword"),
        call.encrypt("1234567890123456789"),
        call.blind_index("1234567890123456789"),
        call.execute(
            SQL_INSERT,
            (3, "eyeonwater.com", "sealedUsername", "theUsernameHash", "sealedPassword", "sealedUuid", "theUuidHash", "Gallons", None),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # no unit asked for: cubic metres, which is what everything is stored in
    payload = {**helper_payload(), "export_unit": ""}
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    hostname.side_effect = ["eyeonwater.com"]
    meter_uuid.side_effect = [""]
    client_class.side_effect = [client]
    resolve_meter.side_effect = ["1234567890123456789"]
    probe.side_effect = [None]
    database.blind_index.side_effect = ["theUuidHash", "theUsernameHash", "theUuidHash"]
    database.encrypt.side_effect = ["sealedUsername", "sealedPassword", "sealedUuid"]
    database.fetch_one.side_effect = [None]
    database.execute.side_effect = [11]
    tested.create_feed(user, payload)
    # No uuid given: the account is asked, and the answer is what gets stored.
    assert client_class.mock_calls == [call("eyeonwater.com", "theUsername", "thePassword", "Gallons")]
    assert resolve_meter.mock_calls == [call(client, "")]
    assert probe.mock_calls == [call(client, "1234567890123456789")]
    reset_mocks()


@patch("usage.commands.water_command.EyeOnWaterClient")
@patch.object(WaterCommand, "_probe")
@patch.object(WaterCommand, "_resolve_meter")
@patch.object(WaterCommand, "_meter_uuid")
@patch.object(WaterCommand, "_hostname")
@patch.object(WaterCommand, "_require_feed")
@patch.object(WaterCommand, "_require_admin")
def test_update_feed(
    require_admin: MagicMock,
    require_feed: MagicMock,
    hostname: MagicMock,
    meter_uuid: MagicMock,
    resolve_meter: MagicMock,
    probe: MagicMock,
    client_class: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    client = MagicMock()

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        hostname.reset_mock()
        meter_uuid.reset_mock()
        resolve_meter.reset_mock()
        probe.reset_mock()
        client_class.reset_mock()
        client.reset_mock()
        database.reset_mock()

    user = helper_user()
    feed = {"id": 11, "house_id": 3, "password": "sealedPassword"}

    # the username is mandatory
    payload = {**helper_payload(), "username": ""}
    require_admin.side_effect = [None]
    require_feed.side_effect = [feed]
    hostname.side_effect = ["eyeonwater.com"]
    meter_uuid.side_effect = ["1234567890123456789"]
    with pytest.raises(AppException) as exc_info:
        tested.update_feed(user, 11, payload)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter the EyeOnWater username."
    assert resolve_meter.mock_calls == []
    assert probe.mock_calls == []
    assert client_class.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # a new password
    payload = helper_payload()
    require_admin.side_effect = [None]
    require_feed.side_effect = [feed]
    hostname.side_effect = ["eyeonwater.com"]
    meter_uuid.side_effect = ["1234567890123456789"]
    client_class.side_effect = [client]
    resolve_meter.side_effect = ["1234567890123456789"]
    probe.side_effect = [None]
    database.encrypt.side_effect = ["sealedUsername", "sealedNewPassword", "sealedUuid"]
    database.blind_index.side_effect = ["theUsernameHash", "theUuidHash"]
    database.execute.side_effect = [11]
    result = tested.update_feed(user, 11, payload)
    expected = {"message": "Water feed updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert hostname.mock_calls == [call(payload)]
    assert meter_uuid.mock_calls == [call(payload)]
    assert client_class.mock_calls == [call("eyeonwater.com", "theUsername", "thePassword", "Gallons")]
    assert resolve_meter.mock_calls == [call(client, "1234567890123456789")]
    assert probe.mock_calls == [call(client, "1234567890123456789")]
    exp_calls = [
        call.encrypt("theUsername"),
        call.blind_index("theUsername"),
        call.encrypt("thePassword"),
        call.encrypt("1234567890123456789"),
        call.blind_index("1234567890123456789"),
        call.execute(
            SQL_UPDATE,
            ("eyeonwater.com", "sealedUsername", "theUsernameHash", "sealedNewPassword", "sealedUuid", "theUuidHash", "Gallons", True, None, None, 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a limit travels twice: once to be stored, once to be compared with the one
    # already there, so that moving it re-arms the alert standing against the old
    hostname.side_effect = ["eyeonwater.com"]
    meter_uuid.side_effect = ["1234567890123456789"]
    client_class.side_effect = [client]
    resolve_meter.side_effect = ["1234567890123456789"]
    probe.side_effect = [None]
    require_admin.side_effect = [None]
    require_feed.side_effect = [{"id": 11, "house_id": 3, "password": "sealedPassword"}]
    database.encrypt.side_effect = ["sealedUsername", "sealedNewPassword", "sealedUuid"]
    database.blind_index.side_effect = ["theUsernameHash", "theUuidHash"]
    database.execute.side_effect = [11]
    result = tested.update_feed(user, 11, {**payload, "daily_max": 0.38})
    assert result == expected
    assert database.mock_calls[-1] == call.execute(
        SQL_UPDATE,
        ("eyeonwater.com", "sealedUsername", "theUsernameHash", "sealedNewPassword", "sealedUuid", "theUuidHash", "Gallons", True, 0.38, 0.38, 11),
    )
    reset_mocks()

    # an empty password keeps the stored one
    payload = {**helper_payload(), "password": "", "active": False}
    require_admin.side_effect = [None]
    require_feed.side_effect = [feed]
    hostname.side_effect = ["eyeonwater.com"]
    meter_uuid.side_effect = ["1234567890123456789"]
    client_class.side_effect = [client]
    resolve_meter.side_effect = ["1234567890123456789"]
    probe.side_effect = [None]
    database.decrypt.side_effect = ["theStoredPassword"]
    database.encrypt.side_effect = ["sealedUsername", "sealedPassword", "sealedUuid"]
    database.blind_index.side_effect = ["theUsernameHash", "theUuidHash"]
    database.execute.side_effect = [11]
    result = tested.update_feed(user, 11, payload)
    assert result == expected
    assert client_class.mock_calls == [call("eyeonwater.com", "theUsername", "theStoredPassword", "Gallons")]
    assert probe.mock_calls == [call(client, "1234567890123456789")]
    exp_calls = [
        call.decrypt("sealedPassword"),
        call.encrypt("theUsername"),
        call.blind_index("theUsername"),
        call.encrypt("theStoredPassword"),
        call.encrypt("1234567890123456789"),
        call.blind_index("1234567890123456789"),
        call.execute(
            SQL_UPDATE,
            ("eyeonwater.com", "sealedUsername", "theUsernameHash", "sealedPassword", "sealedUuid", "theUuidHash", "Gallons", False, None, None, 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(WaterCommand, "_require_feed")
@patch.object(WaterCommand, "_require_admin")
def test_delete_feed(require_admin: MagicMock, require_feed: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        database.reset_mock()

    user = helper_user()
    require_admin.side_effect = [None]
    require_feed.side_effect = [{"id": 11, "house_id": 3, "password": "sealedPassword"}]
    database.execute.side_effect = [11]
    result = tested.delete_feed(user, 11)
    expected = {"message": "Water feed deleted, with everything it had collected."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert database.mock_calls == [call.execute("DELETE FROM water_feeds WHERE id = %s", (11,))]
    reset_mocks()


@patch.object(WaterCommand, "_require_feed")
@patch.object(WaterCommand, "_require_admin")
def test_restart_backfill(require_admin: MagicMock, require_feed: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        database.reset_mock()

    user = helper_user()
    require_admin.side_effect = [None]
    require_feed.side_effect = [{"id": 11, "house_id": 3, "password": "sealedPassword"}]
    database.execute.side_effect = [11]
    result = tested.restart_backfill(user, 11)
    expected = {"message": "History import restarted. It starts within a minute and walks back a month at a time."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    exp_calls = [
        call.execute(
            """
            UPDATE water_feeds
            SET backfill_from = NULL, backfill_done = false, empty_chunks = 0, last_sync_at = NULL
            WHERE id = %s
            """,
            (11,),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.water_command.SeriesPulse")
@patch("usage.commands.water_command.datetime", wraps=datetime)
@patch.object(WaterCommand, "_due")
@patch.object(WaterCommand, "_alert")
@patch.object(WaterCommand, "_latest")
@patch.object(WaterCommand, "_require_house")
def test_series(
    require_house: MagicMock,
    latest: MagicMock,
    alert: MagicMock,
    due: MagicMock,
    mock_datetime: MagicMock,
    pulse: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        latest.reset_mock()
        alert.reset_mock()
        due.reset_mock()
        mock_datetime.reset_mock()
        pulse.reset_mock()
        database.reset_mock()

    user = helper_user()
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

    # unknown range
    require_house.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.series(user, 3, 14, False, 0)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The range must be one of 1, 7, 30, 365 days."
    assert require_house.mock_calls == [call(user, 3)]
    assert latest.mock_calls == []
    assert alert.mock_calls == []
    assert due.mock_calls == []
    assert mock_datetime.mock_calls == []
    assert pulse.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # negative offset
    require_house.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.series(user, 3, 1, False, -1)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The offset counts periods back from now."
    assert require_house.mock_calls == [call(user, 3)]
    assert latest.mock_calls == []
    assert alert.mock_calls == []
    assert due.mock_calls == []
    assert mock_datetime.mock_calls == []
    assert pulse.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    rows = [
        {"bucket": datetime(2026, 9, 15, 11, 0, tzinfo=UTC), "volume": Decimal("0.009628")},
        {"bucket": datetime(2026, 9, 15, 11, 15, tzinfo=UTC), "volume": Decimal("0.000000")},
    ]
    exp_latest = {"at": "2026-09-14T22:29:00+00:00", "volume": 0.0096, "reading": 516.2863}
    exp_alert = {"daily_max": 0.5, "over": True}
    tests = [
        (1, 15, False, 0, "2026-09-14T12:00:00+00:00", "2026-09-15T12:00:00+00:00"),
        (1, 15, True, 0, "2026-09-13T12:00:00+00:00", "2026-09-15T12:00:00+00:00"),
        (7, 60, False, 2, "2026-08-25T12:00:00+00:00", "2026-09-01T12:00:00+00:00"),
    ]
    for days, bucket_minutes, previous, offset, exp_since, exp_until in tests:
        require_house.side_effect = [None]
        mock_datetime.now.side_effect = [now]
        latest.side_effect = [exp_latest]
        alert.side_effect = [exp_alert]
        due.side_effect = [datetime(2026, 9, 15, 12, 4, 0, tzinfo=UTC)]
        pulse.stamp.side_effect = ["theStamp"]
        pulse.next_poll.side_effect = [240]
        database.fetch_all.side_effect = [rows]
        result = tested.series(user, 3, days, previous, offset)
        expected = {
            "days": days,
            "bucket_minutes": bucket_minutes,
            "previous": previous,
            "offset": offset,
            "until": exp_until,
            "unit": "m³",
            "points": [
                {"at": "2026-09-15T11:00:00+00:00", "volume": 0.0096},
                {"at": "2026-09-15T11:15:00+00:00", "volume": 0.0},
            ],
            "latest": exp_latest,
            "alert": exp_alert,
            "stamp": "theStamp",
            "next_poll_seconds": 240,
        }
        assert result == expected
        assert require_house.mock_calls == [call(user, 3)]
        assert latest.mock_calls == [call(3)]
        assert alert.mock_calls == [call(3)]
        assert due.mock_calls == [call(3)]
        assert mock_datetime.mock_calls == [call.now(UTC)]
        assert pulse.mock_calls == [
            call.stamp(expected["points"], exp_latest, exp_alert),
            call.next_poll([datetime(2026, 9, 15, 12, 4, 0, tzinfo=UTC)], now),
        ]
        exp_calls = [call.fetch_all(SQL_SERIES, (timedelta(minutes=bucket_minutes), 3, exp_since, exp_until))]
        assert database.mock_calls == exp_calls
        reset_mocks()


def test__due() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_sql = """
            SELECT MIN(COALESCE(last_sync_at + %s, now())) AS due
            FROM water_feeds WHERE house_id = %s AND active
            """
    # the quarter-hour between pulls plus the minute the loop wakes on: arriving
    # a second early would only cost a request that answers the same thing
    exp_call = call.fetch_one(exp_sql, (timedelta(seconds=960), 3))
    due = datetime(2026, 9, 15, 12, 4, tzinfo=UTC)

    database.fetch_one.side_effect = [{"due": due}]
    result = tested._due(3)
    assert result == due
    assert database.mock_calls == [exp_call]
    reset_mocks()

    # a house with no meter at all: the query answers, the row does not
    database.fetch_one.side_effect = [{"due": None}]
    result = tested._due(3)
    assert result is None
    assert database.mock_calls == [exp_call]
    reset_mocks()

    database.fetch_one.side_effect = [None]
    result = tested._due(3)
    assert result is None
    assert database.mock_calls == [exp_call]
    reset_mocks()


@patch.object(WaterCommand, "_require_house")
def test_alerts(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_calls = [call.fetch_one("SELECT enabled FROM water_alerts WHERE user_id = %s AND house_id = %s", (7, 3))]
    tests: list[tuple[dict[str, Any] | None, bool]] = [(None, False), ({"enabled": False}, False), ({"enabled": True}, True)]
    for row, expected in tests:
        require_house.side_effect = [None]
        database.fetch_one.side_effect = [row]
        result = tested.alerts(user, 3)
        assert result == {"enabled": expected}
        assert require_house.mock_calls == [call(user, 3)]
        assert database.mock_calls == exp_calls
        reset_mocks()


@patch.object(WaterCommand, "_require_house")
def test_set_alerts(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    sql = """
            INSERT INTO water_alerts(user_id, house_id, enabled) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, house_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """
    tests = [(True, "Leak alerts enabled for this house."), (False, "Leak alerts disabled for this house.")]
    for enabled, message in tests:
        require_house.side_effect = [None]
        database.execute.side_effect = [1]
        result = tested.set_alerts(user, {"house_id": 3, "enabled": enabled})
        assert result == {"message": message}
        assert require_house.mock_calls == [call(user, 3)]
        assert database.mock_calls == [call.execute(sql, (7, 3, enabled))]
        reset_mocks()


def test__latest() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # nothing collected yet
    database.fetch_one.side_effect = [None]
    result = tested._latest(3)
    expected: dict[str, Any] = {"at": "", "volume": None, "reading": None}
    assert result == expected
    assert database.mock_calls == [call.fetch_one(SQL_LATEST, (3,))]
    reset_mocks()

    database.fetch_one.side_effect = [
        {
            "measured_at": datetime(2026, 9, 14, 22, 29, tzinfo=UTC),
            "volume": Decimal("0.009628"),
            "reading": Decimal("516.2863"),
        },
    ]
    result = tested._latest(3)
    expected = {"at": "2026-09-14T22:29:00+00:00", "volume": 0.0096, "reading": 516.2863}
    assert result == expected
    assert database.mock_calls == [call.fetch_one(SQL_LATEST, (3,))]
    reset_mocks()

    # a reading the CSV gave in a unit we cannot convert
    database.fetch_one.side_effect = [
        {"measured_at": datetime(2026, 9, 14, 22, 29, tzinfo=UTC), "volume": Decimal("0.0"), "reading": None},
    ]
    result = tested._latest(3)
    expected = {"at": "2026-09-14T22:29:00+00:00", "volume": 0.0, "reading": None}
    assert result == expected
    assert database.mock_calls == [call.fetch_one(SQL_LATEST, (3,))]
    reset_mocks()


@patch("usage.commands.water_command.datetime", wraps=datetime)
def test__probe(mock_datetime: MagicMock) -> None:
    client = MagicMock()

    def reset_mocks() -> None:
        mock_datetime.reset_mock()
        client.reset_mock()

    tested = helper_instance()
    mock_datetime.now.side_effect = [datetime(2026, 9, 15, 12, 0, tzinfo=UTC)]
    client.export.side_effect = [[]]
    result = tested._probe(client, "theUuid")
    assert result is None
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert client.mock_calls == [call.export("theUuid", date(2026, 9, 13), date(2026, 9, 15))]
    reset_mocks()


def test__resolve_meter() -> None:
    client = MagicMock()

    def reset_mocks() -> None:
        client.reset_mock()

    tested = helper_instance()
    one = WaterMeter(uuid="1234567890123456789", meter_id="900112233", timezone="US/Pacific")
    other = WaterMeter(uuid="1111111111111111111", meter_id="999999999")

    # an account with a single meter needs no uuid at all
    client.meters.side_effect = [[one]]
    result = tested._resolve_meter(client, "")
    expected = "1234567890123456789"
    assert result == expected
    assert client.mock_calls == [call.meters()]
    reset_mocks()

    # one that is given is checked against the account
    client.meters.side_effect = [[one, other]]
    result = tested._resolve_meter(client, "1111111111111111111")
    expected = "1111111111111111111"
    assert result == expected
    assert client.mock_calls == [call.meters()]
    reset_mocks()

    # several meters and no choice made: the caller is told what there is
    client.meters.side_effect = [[one, other]]
    with pytest.raises(AppException) as exc_info:
        tested._resolve_meter(client, "")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "This account has several meters. Enter one of these uuids: 1234567890123456789, 1111111111111111111."
    assert client.mock_calls == [call.meters()]
    reset_mocks()

    # a uuid the account does not have
    client.meters.side_effect = [[one]]
    with pytest.raises(AppException) as exc_info:
        tested._resolve_meter(client, "900112233")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "That is the meter ID, not the meter uuid. This meter's uuid is 1234567890123456789."
    assert client.mock_calls == [call.meters()]
    reset_mocks()

    # an account with nothing on it
    client.meters.side_effect = [[]]
    with pytest.raises(AppException) as exc_info:
        tested._resolve_meter(client, "")
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "That EyeOnWater account has no meter on it."
    assert client.mock_calls == [call.meters()]
    reset_mocks()


def test__wrong_meter() -> None:
    tested = WaterCommand
    one = WaterMeter(uuid="1234567890123456789", meter_id="900112233")
    other = WaterMeter(uuid="1111111111111111111", meter_id="999999999")
    tests = [
        ("900112233", [one], "That is the meter ID, not the meter uuid. This meter's uuid is 1234567890123456789."),
        ("nothing", [one, other], "This account has no meter with that uuid. It has: 1234567890123456789, 1111111111111111111."),
    ]
    for wanted, meters, expected in tests:
        result = tested._wrong_meter(wanted, meters)
        assert result == expected


def test__hostname() -> None:
    tested = WaterCommand
    tests = [
        ({}, "eyeonwater.com"),
        ({"hostname": ""}, "eyeonwater.com"),
        ({"hostname": " EyeOnWater.COM "}, "eyeonwater.com"),
        ({"hostname": "eyeonwater.ca"}, "eyeonwater.ca"),
    ]
    for data, expected in tests:
        result = tested._hostname(data)
        assert result == expected

    with pytest.raises(AppException) as exc_info:
        tested._hostname({"hostname": "example.com"})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The EyeOnWater host must be eyeonwater.com or eyeonwater.ca."


def test__meter_uuid() -> None:
    tested = WaterCommand
    tests = [
        ({"meter_uuid": " 1234567890123456789 "}, "1234567890123456789"),
        ({"meter_uuid": "abc-123"}, "abc-123"),
    ]
    for data, expected in tests:
        result = tested._meter_uuid(data)
        assert result == expected

    # Empty is the normal case now: the account is asked.
    for data in [{}, {"meter_uuid": ""}, {"meter_uuid": "  "}]:
        result = tested._meter_uuid(data)
        assert result == ""

    for data in [{"meter_uuid": "a b"}, {"meter_uuid": "a" * 65}]:
        with pytest.raises(AppException) as exc_info:
            tested._meter_uuid(data)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "A meter uuid is letters and digits only."


def test__moment() -> None:
    tested = WaterCommand
    tests: list[tuple[datetime | None, str]] = [
        (None, ""),
        (datetime(2026, 9, 14, 22, 29, tzinfo=UTC), "2026-09-14T22:29:00+00:00"),
    ]
    for value, expected in tests:
        result = tested._moment(value)
        assert result == expected


def test__visible_house_ids() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    user = helper_user()
    database.fetch_all.side_effect = [[{"house_id": 3}, {"house_id": 5}]]
    result = tested._visible_house_ids(user)
    expected = [3, 5]
    assert result == expected
    exp_calls = [call.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (7,))]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__require_admin() -> None:
    tested = WaterCommand
    result = tested._require_admin(helper_user(is_admin=True))
    assert result is None

    with pytest.raises(AppException) as exc_info:
        tested._require_admin(helper_user(is_admin=False))
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Only admins can do this."


@patch.object(WaterCommand, "_visible_house_ids")
def test__require_house(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()

    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()

    database.fetch_one.side_effect = [{"id": 3}]
    visible_house_ids.side_effect = [[5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 3)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()

    database.fetch_one.side_effect = [{"id": 3}]
    visible_house_ids.side_effect = [[3, 5]]
    result = tested._require_house(user, 3)
    assert result is None
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    reset_mocks()


@patch.object(WaterCommand, "_visible_house_ids")
def test__require_feed(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_calls = [
        call.fetch_one(
            "SELECT id, house_id, password_sealed AS password FROM water_feeds WHERE id = %s",
            (11,),
        ),
    ]

    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_feed(user, 11)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The water feed was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == exp_calls
    reset_mocks()

    database.fetch_one.side_effect = [{"id": 11, "house_id": 3, "password": "sealedPassword"}]
    visible_house_ids.side_effect = [[5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_feed(user, 11)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == exp_calls
    reset_mocks()

    database.fetch_one.side_effect = [{"id": 11, "house_id": 3, "password": "sealedPassword"}]
    visible_house_ids.side_effect = [[3]]
    result = tested._require_feed(user, 11)
    expected = {"id": 11, "house_id": 3, "password": "sealedPassword"}
    assert result == expected
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__daily_max() -> None:
    tested = helper_instance()
    tests: list[tuple[dict[str, Any], float | None]] = [
        ({"daily_max": 1.5}, 1.5),
        ({"daily_max": "1.5"}, 1.5),
        ({"daily_max": 0.5000004}, 0.5),
        # the ordinary case: no limit set, and so no alert to send
        ({}, None),
        ({"daily_max": None}, None),
        ({"daily_max": ""}, None),
        ({"daily_max": "  "}, None),
    ]
    for data, expected in tests:
        result = tested._daily_max(data)
        assert result == expected

    # zero would alert on every reading for ever, so it is refused rather than stored
    for bad in [0, -1, "0"]:
        with pytest.raises(AppException) as exc_info:
            tested._daily_max({"daily_max": bad})
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The daily limit must be more than zero, or empty for no alert."

    for bad in ["a lot", []]:
        with pytest.raises(AppException) as exc_info:
            tested._daily_max({"daily_max": bad})
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The daily limit must be a number."


def test__alert() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sql = """
            SELECT SUM(daily_max) AS daily_max, BOOL_OR(over_daily) AS over
            FROM water_feeds WHERE house_id = %s AND active
            """
    exp_calls = [call.fetch_one(sql, (3,))]

    tests: list[tuple[dict[str, Any] | None, dict[str, Any]]] = [
        ({"daily_max": Decimal("0.5"), "over": True}, {"daily_max": 0.5, "over": True}),
        ({"daily_max": Decimal("0.5"), "over": False}, {"daily_max": 0.5, "over": False}),
        # two meters with a limit each make one number for the house
        ({"daily_max": Decimal("0.9"), "over": True}, {"daily_max": 0.9, "over": True}),
        # nobody set one: no number at all, rather than a zero that reads as none
        ({"daily_max": None, "over": None}, {"daily_max": None, "over": False}),
        (None, {"daily_max": None, "over": False}),
    ]
    for row, expected in tests:
        database.fetch_one.side_effect = [row]
        result = tested._alert(3)
        assert result == expected
        assert database.mock_calls == exp_calls
        reset_mocks()
