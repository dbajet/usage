from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.enphase_command import EnphaseCommand
from usage.structures.app_exception import AppException
from usage.structures.enphase_system import EnphaseSystem
from usage.structures.enphase_tokens import EnphaseTokens
from usage.structures.session_user import SessionUser

SQL_FEEDS = """
                SELECT id, client_id_sealed AS client_id, system_id_sealed AS system_id, active,
                       last_sync_at, last_point_at, last_error, backfill_done, fine_from, fine_done,
                       calls_used, calls_budget, calls_month, token_expires_at
                FROM enphase_feeds WHERE house_id = %s AND source = %s ORDER BY id
                """
SQL_COUNTS = "SELECT COUNT(*) AS points, MIN(measured_at) AS first_at FROM enphase_points WHERE feed_id = %s"
SQL_EXISTING = "SELECT id FROM enphase_feeds WHERE house_id = %s AND system_id_hash = %s"
SQL_INSERT = """
            INSERT INTO enphase_feeds(house_id, client_id_sealed, client_secret_sealed, api_key_sealed,
                                      system_id_sealed, system_id_hash, access_token_sealed,
                                      refresh_token_sealed, token_expires_at, calls_budget, production_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """
SQL_UPDATE = """
            UPDATE enphase_feeds
            SET client_id_sealed = %s, client_secret_sealed = %s, api_key_sealed = %s,
                system_id_sealed = %s, system_id_hash = %s, access_token_sealed = %s,
                refresh_token_sealed = %s, token_expires_at = %s, calls_budget = %s,
                active = %s, production_path = %s, last_error = ''
            WHERE id = %s
            """
SQL_RESTART = """
            UPDATE enphase_feeds
            SET backfill_from = NULL, backfill_done = false, fine_from = NULL, fine_done = false, last_sync_at = NULL
            WHERE id = %s
            """
SQL_REQUIRE_FEED = """
            SELECT id, house_id, client_secret_sealed AS client_secret, api_key_sealed AS api_key,
                   access_token_sealed AS access_token, refresh_token_sealed AS refresh_token, token_expires_at
            FROM enphase_feeds WHERE id = %s AND source = %s
            """
SQL_SERIES_DAILY = """
            WITH live AS (
            SELECT date_bin(%s, enphase_points.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   SUM(enphase_points.production) AS production,
                   SUM(enphase_points.consumption) AS consumption,
                   AVG(enphase_points.battery_level) AS battery_level
            FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
            WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
              AND enphase_points.span_minutes = %s
              AND enphase_points.measured_at >= %s AND enphase_points.measured_at < %s
              AND enphase_feeds.source = %s
            GROUP BY bucket
            ), cloud AS (
            SELECT date_bin(%s, enphase_points.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   SUM(enphase_points.production) AS production,
                   SUM(enphase_points.consumption) AS consumption,
                   AVG(enphase_points.battery_level) AS battery_level
            FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
            WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
              AND enphase_points.span_minutes = %s
              AND enphase_points.measured_at >= %s AND enphase_points.measured_at < %s
              AND enphase_feeds.source = %s
            GROUP BY bucket
            )
            SELECT COALESCE(live.bucket, cloud.bucket) AS bucket,
                   COALESCE(live.production, cloud.production) AS production,
                   COALESCE(live.consumption, cloud.consumption) AS consumption,
                   COALESCE(live.battery_level, cloud.battery_level) AS battery_level
            FROM live FULL OUTER JOIN cloud ON cloud.bucket = live.bucket
            ORDER BY bucket
            """
SQL_SERIES_FINE = """
            WITH live AS (
            SELECT date_bin(%s, enphase_points.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   SUM(enphase_points.production) AS production,
                   SUM(enphase_points.consumption) AS consumption,
                   AVG(enphase_points.battery_level) AS battery_level
            FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
            WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
              AND enphase_points.span_minutes < %s
              AND enphase_points.measured_at >= %s AND enphase_points.measured_at < %s
              AND enphase_feeds.source = %s
            GROUP BY bucket
            ), cloud AS (
            SELECT date_bin(%s, enphase_points.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   SUM(enphase_points.production) AS production,
                   SUM(enphase_points.consumption) AS consumption,
                   AVG(enphase_points.battery_level) AS battery_level
            FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
            WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
              AND enphase_points.span_minutes < %s
              AND enphase_points.measured_at >= %s AND enphase_points.measured_at < %s
              AND enphase_feeds.source = %s
            GROUP BY bucket
            )
            SELECT COALESCE(live.bucket, cloud.bucket) AS bucket,
                   COALESCE(live.production, cloud.production) AS production,
                   COALESCE(live.consumption, cloud.consumption) AS consumption,
                   COALESCE(live.battery_level, cloud.battery_level) AS battery_level
            FROM live FULL OUTER JOIN cloud ON cloud.bucket = live.bucket
            ORDER BY bucket
            """
SQL_LATEST_PRODUCTION = """
                SELECT enphase_points.measured_at, enphase_points.production AS value
                FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
                WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
                  AND enphase_points.span_minutes < %s AND enphase_points.production IS NOT NULL
                ORDER BY enphase_points.measured_at DESC LIMIT 1
                """
SQL_LATEST_CONSUMPTION = """
                SELECT enphase_points.measured_at, enphase_points.consumption AS value
                FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
                WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
                  AND enphase_points.span_minutes < %s AND enphase_points.consumption IS NOT NULL
                ORDER BY enphase_points.measured_at DESC LIMIT 1
                """
SQL_LATEST_BATTERY_LEVEL = """
                SELECT enphase_points.measured_at, enphase_points.battery_level AS value
                FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
                WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
                  AND enphase_points.span_minutes < %s AND enphase_points.battery_level IS NOT NULL
                ORDER BY enphase_points.measured_at DESC LIMIT 1
                """


def helper_instance() -> EnphaseCommand:
    return EnphaseCommand(MagicMock(), MagicMock())


def helper_user(is_admin: bool = True) -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane", is_admin=is_admin)


def helper_payload() -> dict[str, Any]:
    return {
        "house_id": 3,
        "client_id": " theClientId ",
        "client_secret": " theClientSecret ",
        "api_key": " theApiKey ",
        "code": " theCode ",
        "system_id": " 3456789 ",
        "calls_budget": 5000,
    }


def helper_tokens() -> EnphaseTokens:
    return EnphaseTokens(
        access_token="theAccessToken",
        refresh_token="theRefreshToken",
        expires_at=datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
    )


def helper_feed_row() -> dict[str, Any]:
    return {
        "id": 11,
        "house_id": 3,
        "client_secret": "sealedSecret",
        "api_key": "sealedKey",
        "access_token": "sealedAccess",
        "refresh_token": "sealedRefresh",
        "token_expires_at": datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
    }


def test___init__() -> None:
    database = MagicMock()
    limiter = MagicMock()
    tested = EnphaseCommand(database, limiter)
    assert tested._database is database
    assert tested._limiter is limiter
    assert database.mock_calls == []
    assert limiter.mock_calls == []


@patch("usage.commands.enphase_command.EnphaseClient")
@patch.object(EnphaseCommand, "_require_admin")
def test_authorize_url(require_admin: MagicMock, client_class: MagicMock) -> None:
    def reset_mocks() -> None:
        require_admin.reset_mock()
        client_class.reset_mock()

    user = helper_user()

    require_admin.side_effect = [None]
    client_class.authorize_url.side_effect = ["https://api.enphaseenergy.com/oauth/authorize?theQuery"]
    tested = helper_instance()
    result = tested.authorize_url(user, "  theClientId  ")
    expected = {"url": "https://api.enphaseenergy.com/oauth/authorize?theQuery"}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert client_class.mock_calls == [call.authorize_url("theClientId")]
    reset_mocks()

    # without the client id there is nothing to send anybody to
    require_admin.side_effect = [None]
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested.authorize_url(user, "   ")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter the application's client id first."
    assert require_admin.mock_calls == [call(user)]
    assert client_class.mock_calls == []
    reset_mocks()


@patch.object(EnphaseCommand, "_local")
@patch.object(EnphaseCommand, "_live")
@patch.object(EnphaseCommand, "_require_house")
@patch.object(EnphaseCommand, "_require_admin")
def test_list_feeds(require_admin: MagicMock, require_house: MagicMock, live: MagicMock, local: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_house.reset_mock()
        live.reset_mock()
        local.reset_mock()
        database.reset_mock()

    exp_live = {"at": "2026-09-16T07:14:00+00:00", "production_power": 600.0,
                "consumption_power": 360.0, "battery_level": 82.0}
    exp_local = {"id": 12, "points": 400, "first_point_at": "2026-09-14T00:00:00+00:00",
                 "last_point_at": "2026-09-16T07:14:00+00:00"}

    user = helper_user()
    row = {
        "id": 11,
        "client_id": "theClientId",
        "system_id": "3456789",
        "active": True,
        "last_sync_at": datetime(2026, 9, 16, 7, 0, tzinfo=UTC),
        "last_point_at": datetime(2026, 9, 16, 6, 45, tzinfo=UTC),
        "last_error": "",
        "backfill_done": True,
        "fine_from": date(2026, 9, 10),
        "fine_done": False,
        "calls_used": 123,
        "calls_budget": 1000,
        "calls_month": date(2026, 9, 1),
        "token_expires_at": datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
    }
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [[row]]
    database.decrypt_rows.side_effect = [[row]]
    database.fetch_one.side_effect = [{"points": 4096, "first_at": datetime(2022, 1, 1, tzinfo=UTC)}]
    live.side_effect = [exp_live]
    local.side_effect = [exp_local]
    result = tested.list_feeds(user, 3)
    expected = {
        "feeds": [
            {
                "id": 11,
                "client_id": "theClientId",
                "system_id": "3456789",
                "active": True,
                "last_sync_at": "2026-09-16T07:00:00+00:00",
                "last_point_at": "2026-09-16T06:45:00+00:00",
                "last_error": "",
                "backfill_done": True,
                "fine_done": False,
                "fine_from": "2026-09-10",
                "calls_used": 123,
                "calls_budget": 1000,
                "calls_month": "2026-09-01",
                "token_expires_at": "2026-09-17T07:14:00+00:00",
                "points": 4096,
                "first_point_at": "2022-01-01T00:00:00+00:00",
            },
        ],
        "live": exp_live,
        "local": exp_local,
    }
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.fetch_all(SQL_FEEDS, (3, "cloud")),
        call.decrypt_rows([row], ("client_id", "system_id")),
        call.fetch_one(SQL_COUNTS, (11,)),
    ]
    assert database.mock_calls == exp_calls
    assert live.mock_calls == [call(3)]
    assert local.mock_calls == [call(3)]
    reset_mocks()

    # a feed with nothing collected, and no count row at all
    bare = {**row, "fine_from": None, "calls_month": None, "last_sync_at": None, "last_point_at": None, "token_expires_at": None}
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [[bare]]
    database.decrypt_rows.side_effect = [[bare]]
    database.fetch_one.side_effect = [None]
    live.side_effect = [exp_live]
    local.side_effect = [exp_local]
    result = tested.list_feeds(user, 3)
    expected = {
        "feeds": [
            {
                "id": 11,
                "client_id": "theClientId",
                "system_id": "3456789",
                "active": True,
                "last_sync_at": "",
                "last_point_at": "",
                "last_error": "",
                "backfill_done": True,
                "fine_done": False,
                "fine_from": "",
                "calls_used": 123,
                "calls_budget": 1000,
                "calls_month": "",
                "token_expires_at": "",
                "points": 0,
                "first_point_at": "",
            },
        ],
        "live": exp_live,
        "local": exp_local,
    }
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.fetch_all(SQL_FEEDS, (3, "cloud")),
        call.decrypt_rows([bare], ("client_id", "system_id")),
        call.fetch_one(SQL_COUNTS, (11,)),
    ]
    assert database.mock_calls == exp_calls
    assert live.mock_calls == [call(3)]
    assert local.mock_calls == [call(3)]
    reset_mocks()


@patch("usage.commands.enphase_command.EnphaseClient")
@patch.object(EnphaseCommand, "_probe")
@patch.object(EnphaseCommand, "_resolve_system")
@patch.object(EnphaseCommand, "_require_house")
@patch.object(EnphaseCommand, "_require_admin")
def test_create_feed(
    require_admin: MagicMock,
    require_house: MagicMock,
    resolve_system: MagicMock,
    probe: MagicMock,
    client_class: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    client = MagicMock()

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_house.reset_mock()
        resolve_system.reset_mock()
        probe.reset_mock()
        client_class.reset_mock()
        database.reset_mock()
        client.reset_mock()

    user = helper_user()
    exp_client_class = [call("theClientId", "theClientSecret", "theApiKey", None, tested._limiter)]

    # the happy path: the code is spent while the form is still open
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    client_class.side_effect = [client]
    client.exchange.side_effect = [helper_tokens()]
    client.production_path = "micro"
    resolve_system.side_effect = ["3456789"]
    probe.side_effect = [None]
    database.blind_index.side_effect = ["hashedSystem", "hashedSystem"]
    database.fetch_one.side_effect = [None]
    database.encrypt.side_effect = [
        "sealedClientId",
        "sealedSecret",
        "sealedKey",
        "sealedSystem",
        "sealedAccess",
        "sealedRefresh",
    ]
    database.execute.side_effect = [11]
    result = tested.create_feed(user, helper_payload())
    expected = {"id": 11, "message": "Enphase feed added. The first import starts within a minute."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    assert client_class.mock_calls == exp_client_class
    assert client.mock_calls == [call.exchange("theCode")]
    assert resolve_system.mock_calls == [call(client, "3456789")]
    assert probe.mock_calls == [call(client, "3456789")]
    exp_calls = [
        call.blind_index("3456789"),
        call.fetch_one(SQL_EXISTING, (3, "hashedSystem")),
        call.encrypt("theClientId"),
        call.encrypt("theClientSecret"),
        call.encrypt("theApiKey"),
        call.encrypt("3456789"),
        call.blind_index("3456789"),
        call.encrypt("theAccessToken"),
        call.encrypt("theRefreshToken"),
        call.execute(
            SQL_INSERT,
            (
                3,
                "sealedClientId",
                "sealedSecret",
                "sealedKey",
                "sealedSystem",
                "hashedSystem",
                "sealedAccess",
                "sealedRefresh",
                "2026-09-17T07:14:00+00:00",
                5000,
                "micro",
            ),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a pair with no stated life stores none
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    client_class.side_effect = [client]
    client.exchange.side_effect = [EnphaseTokens(access_token="theAccessToken", refresh_token="theRefreshToken")]
    client.production_path = "micro"
    resolve_system.side_effect = ["3456789"]
    probe.side_effect = [None]
    database.blind_index.side_effect = ["hashedSystem", "hashedSystem"]
    database.fetch_one.side_effect = [None]
    database.encrypt.side_effect = ["a", "b", "c", "d", "e", "f"]
    database.execute.side_effect = [11]
    result = tested.create_feed(user, helper_payload())
    assert result == expected
    assert database.mock_calls[-1] == call.execute(
        SQL_INSERT,
        (3, "a", "b", "c", "d", "hashedSystem", "e", "f", None, 5000, "micro"),
    )
    reset_mocks()

    # already collected for this house
    require_admin.side_effect = [None]
    require_house.side_effect = [None]
    client_class.side_effect = [client]
    client.exchange.side_effect = [helper_tokens()]
    resolve_system.side_effect = ["3456789"]
    probe.side_effect = [None]
    database.blind_index.side_effect = ["hashedSystem"]
    database.fetch_one.side_effect = [{"id": 11}]
    with pytest.raises(AppException) as exc_info:
        tested.create_feed(user, helper_payload())
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "This system is already collected for this house."
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    assert client_class.mock_calls == exp_client_class
    assert client.mock_calls == [call.exchange("theCode")]
    assert resolve_system.mock_calls == [call(client, "3456789")]
    assert probe.mock_calls == [call(client, "3456789")]
    exp_calls = [call.blind_index("3456789"), call.fetch_one(SQL_EXISTING, (3, "hashedSystem"))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the three application secrets are all required, and so is the code
    tests: list[tuple[dict[str, Any], str]] = [
        ({"client_id": " "}, "Enter the application's client id, client secret and API key."),
        ({"client_secret": ""}, "Enter the application's client id, client secret and API key."),
        ({"api_key": ""}, "Enter the application's client id, client secret and API key."),
        ({"code": "  "}, "Authorise the application first, then paste the code Enphase shows you."),
    ]
    for override, message in tests:
        require_admin.side_effect = [None]
        require_house.side_effect = [None]
        with pytest.raises(AppException) as exc_info:
            tested.create_feed(user, {**helper_payload(), **override})
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == message
        assert require_admin.mock_calls == [call(user)]
        assert require_house.mock_calls == [call(user, 3)]
        assert client_class.mock_calls == []
        assert client.mock_calls == []
        assert resolve_system.mock_calls == []
        assert probe.mock_calls == []
        assert database.mock_calls == []
        reset_mocks()


@patch("usage.commands.enphase_command.EnphaseClient")
@patch.object(EnphaseCommand, "_probe")
@patch.object(EnphaseCommand, "_resolve_system")
@patch.object(EnphaseCommand, "_reauthorize")
@patch.object(EnphaseCommand, "_require_feed")
@patch.object(EnphaseCommand, "_require_admin")
def test_update_feed(
    require_admin: MagicMock,
    require_feed: MagicMock,
    reauthorize: MagicMock,
    resolve_system: MagicMock,
    probe: MagicMock,
    client_class: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    client = MagicMock()

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        reauthorize.reset_mock()
        resolve_system.reset_mock()
        probe.reset_mock()
        client_class.reset_mock()
        database.reset_mock()
        client.reset_mock()

    user = helper_user()
    row = helper_feed_row()
    payload = {
        "client_id": " theClientId ",
        "client_secret": " theClientSecret ",
        "api_key": " theApiKey ",
        "code": " theCode ",
        "system_id": " 3456789 ",
        "calls_budget": 5000,
        "active": True,
    }

    # everything supplied afresh: nothing has to be unsealed
    require_admin.side_effect = [None]
    require_feed.side_effect = [row]
    reauthorize.side_effect = [helper_tokens()]
    client_class.side_effect = [client]
    client.tokens = helper_tokens()
    client.production_path = "micro"
    resolve_system.side_effect = ["3456789"]
    probe.side_effect = [None]
    database.encrypt.side_effect = [
        "sealedClientId",
        "sealedSecret",
        "sealedKey",
        "sealedSystem",
        "sealedAccess",
        "sealedRefresh",
    ]
    database.blind_index.side_effect = ["hashedSystem"]
    database.execute.side_effect = [11]
    result = tested.update_feed(user, 11, payload)
    expected = {"message": "Enphase feed updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert reauthorize.mock_calls == [call(row, "theClientId", "theClientSecret", "theApiKey", "theCode")]
    assert client_class.mock_calls == [call("theClientId", "theClientSecret", "theApiKey", helper_tokens(), tested._limiter)]
    assert client.mock_calls == []
    assert resolve_system.mock_calls == [call(client, "3456789")]
    assert probe.mock_calls == [call(client, "3456789")]
    exp_calls = [
        call.encrypt("theClientId"),
        call.encrypt("theClientSecret"),
        call.encrypt("theApiKey"),
        call.encrypt("3456789"),
        call.blind_index("3456789"),
        call.encrypt("theAccessToken"),
        call.encrypt("theRefreshToken"),
        call.execute(
            SQL_UPDATE,
            (
                "sealedClientId",
                "sealedSecret",
                "sealedKey",
                "sealedSystem",
                "hashedSystem",
                "sealedAccess",
                "sealedRefresh",
                "2026-09-17T07:14:00+00:00",
                5000,
                True,
                "micro",
                11,
            ),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the secret and the key left empty: the stored ones are unsealed and kept
    require_admin.side_effect = [None]
    require_feed.side_effect = [row]
    database.decrypt.side_effect = ["theApiKey", "theClientSecret"]
    reauthorize.side_effect = [helper_tokens()]
    client_class.side_effect = [client]
    client.tokens = EnphaseTokens(access_token="theAccessToken", refresh_token="theRefreshToken")
    client.production_path = "micro"
    resolve_system.side_effect = ["3456789"]
    probe.side_effect = [None]
    database.encrypt.side_effect = ["a", "b", "c", "d", "e", "f"]
    database.blind_index.side_effect = ["hashedSystem"]
    database.execute.side_effect = [11]
    result = tested.update_feed(user, 11, {**payload, "client_secret": "", "api_key": "", "code": "", "active": False, "calls_budget": 0})
    assert result == expected
    assert reauthorize.mock_calls == [call(row, "theClientId", "theClientSecret", "theApiKey", "")]
    exp_calls = [
        call.decrypt("sealedKey"),
        call.decrypt("sealedSecret"),
        call.encrypt("theClientId"),
        call.encrypt("theClientSecret"),
        call.encrypt("theApiKey"),
        call.encrypt("3456789"),
        call.blind_index("3456789"),
        call.encrypt("theAccessToken"),
        call.encrypt("theRefreshToken"),
        # no budget given falls back to the free plan's, and no stated life stores none
        call.execute(SQL_UPDATE, ("a", "b", "c", "d", "hashedSystem", "e", "f", None, 1000, False, "micro", 11)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the client id is the one thing that cannot be inferred
    require_admin.side_effect = [None]
    require_feed.side_effect = [row]
    database.decrypt.side_effect = ["theApiKey"]
    with pytest.raises(AppException) as exc_info:
        tested.update_feed(user, 11, {**payload, "client_id": "  "})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter the application's client id."
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert reauthorize.mock_calls == []
    assert client_class.mock_calls == []
    assert client.mock_calls == []
    assert resolve_system.mock_calls == []
    assert probe.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()


@patch("usage.commands.enphase_command.EnphaseClient")
def test__reauthorize(client_class: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    client = MagicMock()

    def reset_mocks() -> None:
        client_class.reset_mock()
        database.reset_mock()
        client.reset_mock()

    row = helper_feed_row()

    # no code: the stored pair has to keep working on its own
    database.decrypt.side_effect = ["theAccessToken", "theRefreshToken"]
    result = tested._reauthorize(row, "theClientId", "theClientSecret", "theApiKey", "")
    expected = helper_tokens()
    assert result == expected
    assert client_class.mock_calls == []
    assert client.mock_calls == []
    assert database.mock_calls == [call.decrypt("sealedAccess"), call.decrypt("sealedRefresh")]
    reset_mocks()

    # a fresh code starts the authorisation over
    database.decrypt.side_effect = ["theAccessToken", "theRefreshToken"]
    client_class.side_effect = [client]
    client.exchange.side_effect = [helper_tokens()]
    result = tested._reauthorize(row, "theClientId", "theClientSecret", "theApiKey", "theCode")
    assert result == expected
    assert client_class.mock_calls == [call("theClientId", "theClientSecret", "theApiKey", None, tested._limiter)]
    assert client.mock_calls == [call.exchange("theCode")]
    assert database.mock_calls == [call.decrypt("sealedAccess"), call.decrypt("sealedRefresh")]
    reset_mocks()


@patch.object(EnphaseCommand, "_require_feed")
@patch.object(EnphaseCommand, "_require_admin")
def test_delete_feed(require_admin: MagicMock, require_feed: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        database.reset_mock()

    user = helper_user()
    require_admin.side_effect = [None]
    require_feed.side_effect = [helper_feed_row()]
    database.execute.side_effect = [11]
    result = tested.delete_feed(user, 11)
    expected = {"message": "Enphase feed deleted, with everything it had collected."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert database.mock_calls == [call.execute("DELETE FROM enphase_feeds WHERE id = %s", (11,))]
    reset_mocks()


@patch.object(EnphaseCommand, "_require_feed")
@patch.object(EnphaseCommand, "_require_admin")
def test_restart_backfill(require_admin: MagicMock, require_feed: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        database.reset_mock()

    user = helper_user()
    require_admin.side_effect = [None]
    require_feed.side_effect = [helper_feed_row()]
    database.execute.side_effect = [11]
    result = tested.restart_backfill(user, 11)
    expected = {"message": "History import restarted. It starts within a minute, budget permitting."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert database.mock_calls == [call.execute(SQL_RESTART, (11,))]
    reset_mocks()


@patch("usage.commands.enphase_command.SeriesPulse")
@patch("usage.commands.enphase_command.datetime", wraps=datetime)
@patch.object(EnphaseCommand, "_due")
@patch.object(EnphaseCommand, "_live")
@patch.object(EnphaseCommand, "_latest")
@patch.object(EnphaseCommand, "_require_house")
def test_series(
    require_house: MagicMock,
    latest: MagicMock,
    live: MagicMock,
    due: MagicMock,
    mock_datetime: MagicMock,
    pulse: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        latest.reset_mock()
        live.reset_mock()
        due.reset_mock()
        mock_datetime.reset_mock()
        pulse.reset_mock()
        database.reset_mock()

    user = helper_user()
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)

    # unknown range
    require_house.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.series(user, 3, 14, False, 0)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The range must be one of 1, 7, 30, 365 days."
    assert require_house.mock_calls == [call(user, 3)]
    assert latest.mock_calls == []
    assert live.mock_calls == []
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
    assert live.mock_calls == []
    assert due.mock_calls == []
    assert mock_datetime.mock_calls == []
    assert pulse.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    rows = [
        {
            "bucket": datetime(2026, 9, 16, 11, 0, tzinfo=UTC),
            "production": Decimal("0.412000"),
            "consumption": Decimal("0.233000"),
            "battery_level": Decimal("87.50"),
        },
        {
            "bucket": datetime(2026, 9, 16, 11, 15, tzinfo=UTC),
            "production": None,
            "consumption": Decimal("0.190000"),
            "battery_level": None,
        },
    ]
    exp_points = [
        {"at": "2026-09-16T11:00:00+00:00", "production": 0.412, "consumption": 0.233, "battery_level": 87.5},
        {"at": "2026-09-16T11:15:00+00:00", "production": None, "consumption": 0.19, "battery_level": None},
    ]
    exp_latest = {"at": "2026-09-16T06:45:00+00:00", "production": 0.412, "consumption": 0.233, "battery_level": 87.5}
    exp_live = {"at": "2026-09-16T07:14:00+00:00", "production_power": 600.0,
                "consumption_power": 360.0, "battery_level": 82.0}
    exp_due = datetime(2026, 9, 16, 12, 0, 59, tzinfo=UTC)
    # a day and a week come from the quarter-hours; a month and a year from the
    # daily totals, and never from both at once
    tests = [
        (1, 15, False, 0, SQL_SERIES_FINE, False, "2026-09-15T12:00:00+00:00", "2026-09-16T12:00:00+00:00"),
        (1, 15, True, 0, SQL_SERIES_FINE, False, "2026-09-14T12:00:00+00:00", "2026-09-16T12:00:00+00:00"),
        (7, 60, False, 2, SQL_SERIES_FINE, False, "2026-08-26T12:00:00+00:00", "2026-09-02T12:00:00+00:00"),
        (30, 1440, False, 0, SQL_SERIES_DAILY, True, "2026-08-17T12:00:00+00:00", "2026-09-16T12:00:00+00:00"),
        (365, 1440, False, 0, SQL_SERIES_DAILY, True, "2025-09-16T12:00:00+00:00", "2026-09-16T12:00:00+00:00"),
    ]
    for days, bucket_minutes, previous, offset, sql, daily, exp_since, exp_until in tests:
        require_house.side_effect = [None]
        mock_datetime.now.side_effect = [now]
        latest.side_effect = [exp_latest]
        live.side_effect = [exp_live]
        due.side_effect = [[exp_due, None]]
        pulse.stamp.side_effect = ["theStamp"]
        pulse.next_poll.side_effect = [59]
        database.fetch_all.side_effect = [rows]
        result = tested.series(user, 3, days, previous, offset)
        expected = {
            "days": days,
            "bucket_minutes": bucket_minutes,
            "previous": previous,
            "offset": offset,
            "until": exp_until,
            "unit": "kWh",
            "daily": daily,
            "points": exp_points,
            "latest": exp_latest,
            "live": exp_live,
            "stamp": "theStamp",
            "next_poll_seconds": 59,
        }
        assert result == expected
        assert require_house.mock_calls == [call(user, 3)]
        assert latest.mock_calls == [call(3)]
        assert live.mock_calls == [call(3)]
        assert due.mock_calls == [call(3)]
        assert mock_datetime.mock_calls == [call.now(UTC)]
        assert pulse.mock_calls == [
            call.stamp(exp_points, exp_latest, exp_live),
            call.next_poll([exp_due, None], now),
        ]
        window = (timedelta(minutes=bucket_minutes), 3, 1440, exp_since, exp_until)
        # the same window asked twice, once of each source, so neither is summed
        exp_calls = [call.fetch_all(sql, (*window, "local", *window, "cloud"))]
        assert database.mock_calls == exp_calls
        reset_mocks()


def test__due() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_gateway = call.fetch_one("SELECT updated_at, push_seconds FROM enphase_live WHERE house_id = %s", (3,))
    exp_cloud = call.fetch_one(
        """
            SELECT MIN(COALESCE(last_sync_at + %s, now())) AS due
            FROM enphase_feeds WHERE house_id = %s AND active AND source = %s
            """,
        # the floor of the pace, not the pace: the page may look a little early
        # but never sleeps past the answer
        (timedelta(seconds=960), 3, "cloud"),
    )
    exp_calls = [exp_gateway, exp_cloud]
    pushed = datetime(2026, 9, 16, 11, 59, tzinfo=UTC)
    synced = datetime(2026, 9, 16, 12, 11, tzinfo=UTC)

    # both feeds, each on its own clock
    database.fetch_one.side_effect = [{"updated_at": pushed, "push_seconds": 60}, {"due": synced}]
    result = tested._due(3)
    assert result == [datetime(2026, 9, 16, 12, 0, tzinfo=UTC), synced]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # one push seen and no second to measure against: the assumed cadence
    database.fetch_one.side_effect = [{"updated_at": pushed, "push_seconds": None}, {"due": synced}]
    result = tested._due(3)
    assert result == [datetime(2026, 9, 16, 12, 9, tzinfo=UTC), synced]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a house on the cloud alone, and one on the gateway alone
    database.fetch_one.side_effect = [None, {"due": synced}]
    result = tested._due(3)
    assert result == [None, synced]
    assert database.mock_calls == exp_calls
    reset_mocks()

    database.fetch_one.side_effect = [{"updated_at": pushed, "push_seconds": 60}, {"due": None}]
    result = tested._due(3)
    assert result == [datetime(2026, 9, 16, 12, 0, tzinfo=UTC), None]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # neither: nothing to date the graph by
    database.fetch_one.side_effect = [None, None]
    result = tested._due(3)
    assert result == [None, None]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__point() -> None:
    tested = helper_instance()
    tests: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (
            {
                "bucket": datetime(2026, 9, 16, 11, 0, tzinfo=UTC),
                "production": Decimal("0.4123456"),
                "consumption": Decimal("0.2330000"),
                "battery_level": Decimal("87.44"),
            },
            {"at": "2026-09-16T11:00:00+00:00", "production": 0.4123, "consumption": 0.233, "battery_level": 87.4},
        ),
        (
            {
                "bucket": datetime(2026, 9, 16, 11, 0, tzinfo=UTC),
                "production": None,
                "consumption": None,
                "battery_level": None,
            },
            {"at": "2026-09-16T11:00:00+00:00", "production": None, "consumption": None, "battery_level": None},
        ),
    ]
    for row, expected in tests:
        result = tested._point(row)
        assert result == expected


def test__latest() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_calls = [
        call.fetch_one(SQL_LATEST_PRODUCTION, (3, 1440)),
        call.fetch_one(SQL_LATEST_CONSUMPTION, (3, 1440)),
        call.fetch_one(SQL_LATEST_BATTERY_LEVEL, (3, 1440)),
    ]

    # each stream is found on its own, and the newest of the three names the moment
    database.fetch_one.side_effect = [
        {"measured_at": datetime(2026, 9, 16, 6, 30, tzinfo=UTC), "value": Decimal("0.412000")},
        {"measured_at": datetime(2026, 9, 16, 6, 45, tzinfo=UTC), "value": Decimal("0.233000")},
        {"measured_at": datetime(2026, 9, 16, 6, 15, tzinfo=UTC), "value": Decimal("87.50")},
    ]
    result = tested._latest(3)
    expected = {
        "at": "2026-09-16T06:45:00+00:00",
        "production": 0.412,
        "consumption": 0.233,
        "battery_level": 87.5,
    }
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a system with no batteries answers the third call with nothing, and the
    # other two tiles must still show their readings
    database.fetch_one.side_effect = [
        {"measured_at": datetime(2026, 9, 16, 6, 30, tzinfo=UTC), "value": Decimal("0.412000")},
        {"measured_at": datetime(2026, 9, 16, 6, 30, tzinfo=UTC), "value": Decimal("0.233000")},
        None,
    ]
    result = tested._latest(3)
    expected = {
        "at": "2026-09-16T06:30:00+00:00",
        "production": 0.412,
        "consumption": 0.233,
        "battery_level": None,
    }
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()

    # nothing collected at all
    database.fetch_one.side_effect = [None, None, None]
    result = tested._latest(3)
    expected = {"at": "", "production": None, "consumption": None, "battery_level": None}
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__resolve_system() -> None:
    tested = helper_instance()
    client = MagicMock()

    def reset_mocks() -> None:
        client.reset_mock()

    one = EnphaseSystem(system_id="3456789", name="Dougmar", status="normal")
    other = EnphaseSystem(system_id="987654", name="Fremur", status="normal")

    # a single system needs no choosing at all
    client.systems.side_effect = [[one]]
    result = tested._resolve_system(client, "")
    expected = "3456789"
    assert result == expected
    assert client.mock_calls == [call.systems()]
    reset_mocks()

    # a named one, checked against what the account actually has
    client.systems.side_effect = [[one, other]]
    result = tested._resolve_system(client, "987654")
    expected = "987654"
    assert result == expected
    assert client.mock_calls == [call.systems()]
    reset_mocks()

    # several, and none named: the choice belongs to a person
    client.systems.side_effect = [[one, other]]
    with pytest.raises(AppException) as exc_info:
        tested._resolve_system(client, "")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "This account has several systems. Enter one of these ids: 3456789, 987654."
    assert client.mock_calls == [call.systems()]
    reset_mocks()

    # a number that is wrong would answer with empty days rather than a refusal
    client.systems.side_effect = [[one]]
    with pytest.raises(AppException) as exc_info:
        tested._resolve_system(client, "111111")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "This account has no system with that id. It has: 3456789 (Dougmar)."
    assert client.mock_calls == [call.systems()]
    reset_mocks()

    # an account with nothing on it
    client.systems.side_effect = [[]]
    with pytest.raises(AppException) as exc_info:
        tested._resolve_system(client, "")
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "That Enphase account has no system on it."
    assert client.mock_calls == [call.systems()]
    reset_mocks()


def test__wrong_system() -> None:
    tested = helper_instance()
    tests: list[tuple[list[EnphaseSystem], str]] = [
        (
            [EnphaseSystem(system_id="3456789", name="Dougmar")],
            "This account has no system with that id. It has: 3456789 (Dougmar).",
        ),
        (
            [EnphaseSystem(system_id="3456789"), EnphaseSystem(system_id="987654", name="Fremur")],
            "This account has no system with that id. It has: 3456789, 987654 (Fremur).",
        ),
    ]
    for systems, expected in tests:
        result = tested._wrong_system(systems)
        assert result == expected


@patch("usage.commands.enphase_command.datetime", wraps=datetime)
def test__probe(mock_datetime: MagicMock) -> None:
    client = MagicMock()

    def reset_mocks() -> None:
        mock_datetime.reset_mock()
        client.reset_mock()

    mock_datetime.now.side_effect = [datetime(2026, 9, 16, 7, 14, tzinfo=UTC)]
    client.production.side_effect = [[]]
    tested = helper_instance()
    result = tested._probe(client, "3456789")
    assert result is None
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert client.mock_calls == [call.production("3456789", date(2026, 9, 16))]
    reset_mocks()


def test__budget() -> None:
    tested = helper_instance()
    tests: list[tuple[dict[str, Any], int]] = [
        ({"calls_budget": 5000}, 5000),
        ({"calls_budget": "5000"}, 5000),
        # nothing given: the free plan's allowance
        ({}, 1000),
        ({"calls_budget": 0}, 1000),
        ({"calls_budget": None}, 1000),
    ]
    for data, expected in tests:
        result = tested._budget(data)
        assert result == expected

    with pytest.raises(AppException) as exc_info:
        tested._budget({"calls_budget": -5})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The monthly call budget must be a positive number."


def test__system_id() -> None:
    tested = helper_instance()
    tests: list[tuple[dict[str, Any], str]] = [
        ({"system_id": " 3456789 "}, "3456789"),
        # empty is allowed: the account is asked instead
        ({}, ""),
        ({"system_id": "  "}, ""),
    ]
    for data, expected in tests:
        result = tested._system_id(data)
        assert result == expected

    for bad in ["34-56789", "abc", "3456789012345678901234"]:
        with pytest.raises(AppException) as exc_info:
            tested._system_id({"system_id": bad})
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "An Enphase system id is digits only."


def test__rounded() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, int, float | None]] = [
        (Decimal("0.4123456"), 4, 0.4123),
        (Decimal("87.44"), 1, 87.4),
        (0.412, 4, 0.412),
        (None, 4, None),
    ]
    for value, digits, expected in tests:
        result = tested._rounded(value, digits)
        assert result == expected


def test__moment() -> None:
    tested = helper_instance()
    tests: list[tuple[datetime | None, str]] = [
        (datetime(2026, 9, 16, 7, 14, tzinfo=UTC), "2026-09-16T07:14:00+00:00"),
        (None, ""),
    ]
    for value, expected in tests:
        result = tested._moment(value)
        assert result == expected


def test__visible_house_ids() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sql = "SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id"
    database.fetch_all.side_effect = [[{"house_id": 3}, {"house_id": 5}]]
    result = tested._visible_house_ids(helper_user())
    expected = [3, 5]
    assert result == expected
    assert database.mock_calls == [call.fetch_all(sql, (7,))]
    reset_mocks()


def test__require_admin() -> None:
    tested = helper_instance()
    result = tested._require_admin(helper_user())
    assert result is None

    with pytest.raises(AppException) as exc_info:
        tested._require_admin(helper_user(False))
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Only admins can do this."


@patch.object(EnphaseCommand, "_visible_house_ids")
def test__require_house(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    sql = "SELECT id FROM houses WHERE id = %s"

    database.fetch_one.side_effect = [{"id": 3}]
    visible_house_ids.side_effect = [[3, 5]]
    result = tested._require_house(user, 3)
    assert result is None
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one(sql, (3,))]
    reset_mocks()

    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [call.fetch_one(sql, (3,))]
    reset_mocks()

    database.fetch_one.side_effect = [{"id": 9}]
    visible_house_ids.side_effect = [[3, 5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 9)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one(sql, (9,))]
    reset_mocks()


@patch.object(EnphaseCommand, "_visible_house_ids")
def test__require_feed(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    row = helper_feed_row()

    database.fetch_one.side_effect = [row]
    visible_house_ids.side_effect = [[3, 5]]
    result = tested._require_feed(user, 11)
    assert result == row
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one(SQL_REQUIRE_FEED, (11, "cloud"))]
    reset_mocks()

    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_feed(user, 11)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The Enphase feed was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [call.fetch_one(SQL_REQUIRE_FEED, (11, "cloud"))]
    reset_mocks()

    database.fetch_one.side_effect = [{**row, "house_id": 9}]
    visible_house_ids.side_effect = [[3, 5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_feed(user, 11)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [call.fetch_one(SQL_REQUIRE_FEED, (11, "cloud"))]
    reset_mocks()


def test__local() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sql = """
            SELECT enphase_feeds.id, COUNT(enphase_points.id) AS points,
                   MIN(enphase_points.measured_at) AS first_at, MAX(enphase_points.measured_at) AS last_at
            FROM enphase_feeds LEFT JOIN enphase_points ON enphase_points.feed_id = enphase_feeds.id
            WHERE enphase_feeds.house_id = %s AND enphase_feeds.source = %s
            GROUP BY enphase_feeds.id
            """
    exp_calls = [call.fetch_one(sql, (3, "local"))]

    database.fetch_one.side_effect = [
        {
            "id": 12,
            "points": 400,
            "first_at": datetime(2026, 9, 14, tzinfo=UTC),
            "last_at": datetime(2026, 9, 16, 7, 14, tzinfo=UTC),
        },
    ]
    result = tested._local(3)
    expected = {
        "id": 12,
        "points": 400,
        "first_point_at": "2026-09-14T00:00:00+00:00",
        "last_point_at": "2026-09-16T07:14:00+00:00",
    }
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a house with no push feed at all: nothing, rather than a zeroed one
    database.fetch_one.side_effect = [None]
    result = tested._local(3)
    expected = {"id": 0, "points": 0, "first_point_at": "", "last_point_at": ""}
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__live() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sql = """
            SELECT measured_at, production_power, consumption_power, battery_level
            FROM enphase_live WHERE house_id = %s
            """
    exp_calls = [call.fetch_one(sql, (3,))]

    database.fetch_one.side_effect = [
        {
            "measured_at": datetime(2026, 9, 16, 7, 14, tzinfo=UTC),
            "production_power": Decimal("600.000"),
            "consumption_power": Decimal("360.000"),
            "battery_level": Decimal("82.00"),
        },
    ]
    result = tested._live(3)
    expected = {
        "at": "2026-09-16T07:14:00+00:00",
        "production_power": 600.0,
        "consumption_power": 360.0,
        "battery_level": 82.0,
    }
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a house on the cloud feed alone has no live reading, and says so with an
    # empty instant: nothing at all is not the same fact as panels making nothing
    database.fetch_one.side_effect = [None]
    result = tested._live(3)
    expected = {"at": "", "production_power": None, "consumption_power": None, "battery_level": None}
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()
