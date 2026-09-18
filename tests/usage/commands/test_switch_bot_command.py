from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.switch_bot_command import SwitchBotCommand
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser
from usage.structures.settings import Settings
from usage.libraries.switch_bot_hubs import SwitchBotHubs
from usage.structures.switch_bot_device import SwitchBotDevice

SQL_FEEDS = """
                SELECT id, token_sealed AS token, hub_ids_sealed AS hub_ids, active,
                       last_sync_at, last_point_at, last_error, webhook_at, webhook_error,
                       last_event_at, created_at
                FROM switchbot_feeds WHERE house_id = %s ORDER BY id
                """
SQL_EXISTING = "SELECT id FROM switchbot_feeds WHERE house_id = %s"
SQL_INSERT = """
            INSERT INTO switchbot_feeds(house_id, token_sealed, token_hash, secret_sealed, hub_ids_sealed,
                                        event_token_sealed, event_token_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """
SQL_UPDATE = """
            UPDATE switchbot_feeds
            SET token_sealed = %s, token_hash = %s, secret_sealed = %s, hub_ids_sealed = %s,
                active = %s, last_error = ''
            WHERE id = %s
            """
SQL_FEED = (
    "SELECT id, house_id, token_sealed AS token, secret_sealed AS secret, "
    "event_token_sealed AS event_token FROM switchbot_feeds WHERE id = %s"
)


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


def helper_instance(base_url: str = "https://usage.example.com") -> SwitchBotCommand:
    return SwitchBotCommand(MagicMock(), helper_settings(base_url), MagicMock())


def helper_user(is_admin: bool = True) -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane", is_admin=is_admin)


def helper_feed() -> dict[str, Any]:
    return {
        "id": 11,
        "house_id": 3,
        "token": "sealedToken",
        "secret": "sealedSecret",
        "event_token": "sealedEventToken",
    }


def helper_devices() -> list[SwitchBotDevice]:
    return [
        SwitchBotDevice(device_id="C271111EC0AB", name="Grenier", device_type="Meter", hub_id="FA7310762361"),
        SwitchBotDevice(device_id="D382222FD1BC", name="Dehors", device_type="WoIOSensor", hub_id="FA7310762361"),
        # the hub itself, which names no hub of its own
        SwitchBotDevice(device_id="FA7310762361", name="Hub Fremur", device_type="Hub 2", hub_id=""),
        SwitchBotDevice(device_id="E493333GE2CD", name="Salon", device_type="Meter", hub_id="BB2210762399"),
    ]


def test___init__() -> None:
    database = MagicMock()
    settings = helper_settings()
    limiter = MagicMock()
    tested = SwitchBotCommand(database, settings, limiter)
    assert tested._database is database
    assert tested._settings is settings
    assert tested._limiter is limiter


@patch.object(SwitchBotCommand, "_picker")
@patch.object(SwitchBotCommand, "_require_house")
@patch.object(SwitchBotCommand, "_require_admin")
def test_hubs(require_admin: MagicMock, require_house: MagicMock, picker: MagicMock) -> None:
    tested = helper_instance()

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_house.reset_mock()
        picker.reset_mock()

    user = helper_user()
    hubs = [{"hub_id": "FA7310762361", "name": "Hub Fremur", "devices": ["Grenier"]}]

    picker.side_effect = [hubs]
    result = tested.hubs(user, {"house_id": 3, "token": "theToken", "secret": "theSecret"})
    expected = {"hubs": hubs}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    assert picker.mock_calls == [call("theToken", "theSecret")]
    reset_mocks()


@patch.object(SwitchBotCommand, "_picker")
@patch.object(SwitchBotCommand, "_require_feed")
@patch.object(SwitchBotCommand, "_require_admin")
def test_feed_hubs(require_admin: MagicMock, require_feed: MagicMock, picker: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        picker.reset_mock()
        database.reset_mock()

    user = helper_user()
    hubs = [{"hub_id": "FA7310762361", "name": "Hub Fremur", "devices": ["Grenier"]}]

    require_feed.side_effect = [helper_feed()]
    database.decrypt.side_effect = ["theToken", "theSecret"]
    picker.side_effect = [hubs]
    result = tested.feed_hubs(user, 11)
    expected = {"hubs": hubs}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert picker.mock_calls == [call("theToken", "theSecret")]
    assert database.mock_calls == [call.decrypt("sealedToken"), call.decrypt("sealedSecret")]
    reset_mocks()


@patch.object(SwitchBotCommand, "_require_house")
@patch.object(SwitchBotCommand, "_require_admin")
def test_list_feeds(require_admin: MagicMock, require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    rows = [
        {
            "id": 11,
            "token": "theVeryLongToken",
            "hub_ids": "BB2210762399,FA7310762361",
            "active": True,
            "last_sync_at": datetime(2026, 9, 17, 14, 2, tzinfo=UTC),
            "last_point_at": datetime(2026, 9, 17, 13, 52, tzinfo=UTC),
            "last_error": "",
            "webhook_at": datetime(2026, 9, 18, 12, 30, tzinfo=UTC),
            "webhook_error": "",
            "last_event_at": datetime(2026, 9, 18, 12, 41, tzinfo=UTC),
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        },
        {
            "id": 12,
            "token": "theOtherToken",
            "hub_ids": "",
            "active": False,
            "last_sync_at": None,
            "last_point_at": None,
            "last_error": "SwitchBot could not be reached.",
            "webhook_at": None,
            "webhook_error": "The app has no public https address, so SwitchBot has nowhere to post events.",
            "last_event_at": None,
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        },
    ]
    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [rows]
    result = tested.list_feeds(user, 3)
    expected = {
        "feeds": [
            {
                "id": 11,
                "token_tail": "gToken",
                "hub_ids": ["BB2210762399", "FA7310762361"],
                "active": True,
                "last_sync_at": "2026-09-17T14:02:00+00:00",
                "last_point_at": "2026-09-17T13:52:00+00:00",
                "last_error": "",
                "webhook_at": "2026-09-18T12:30:00+00:00",
                "webhook_error": "",
                "last_event_at": "2026-09-18T12:41:00+00:00",
            },
            {
                "id": 12,
                "token_tail": "rToken",
                "hub_ids": [],
                "active": False,
                "last_sync_at": "",
                "last_point_at": "",
                "last_error": "SwitchBot could not be reached.",
                "webhook_at": "",
                "webhook_error": "The app has no public https address, so SwitchBot has nowhere to post events.",
                "last_event_at": "",
            },
        ],
    }
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.fetch_all(SQL_FEEDS, (3,)),
        call.decrypt_rows(rows, ("token", "hub_ids")),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.switch_bot_command.secrets.token_urlsafe")
@patch.object(SwitchBotCommand, "_hubs_of")
@patch.object(SwitchBotCommand, "_resolve_hubs")
@patch.object(SwitchBotCommand, "_require_house")
@patch.object(SwitchBotCommand, "_require_admin")
def test_create_feed(
    require_admin: MagicMock,
    require_house: MagicMock,
    resolve_hubs: MagicMock,
    hubs_of: MagicMock,
    token_urlsafe: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    hubs = SwitchBotHubs(helper_devices())

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_house.reset_mock()
        resolve_hubs.reset_mock()
        hubs_of.reset_mock()
        token_urlsafe.reset_mock()
        database.reset_mock()

    user = helper_user()
    payload = {"house_id": 3, "token": "theToken", "secret": "theSecret", "hub_ids": ["FA7310762361"]}

    # added
    hubs_of.side_effect = [hubs]
    resolve_hubs.side_effect = [["BB2210762399", "FA7310762361"]]
    database.blind_index.side_effect = ["theTokenHash", "theEventHash"]
    database.fetch_one.side_effect = [None]
    database.encrypt.side_effect = ["sealedToken", "sealedSecret", "sealedHubs", "sealedEventToken"]
    database.execute.side_effect = [11]
    token_urlsafe.side_effect = ["theEventToken"]
    result = tested.create_feed(user, payload)
    expected = {"id": 11, "message": "SwitchBot feed added. The first readings arrive within a minute."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    assert resolve_hubs.mock_calls == [call(hubs, payload)]
    assert hubs_of.mock_calls == [call("theToken", "theSecret")]
    exp_calls = [
        call.fetch_one(SQL_EXISTING, (3,)),
        call.encrypt("theToken"),
        call.blind_index("theToken"),
        call.encrypt("theSecret"),
        call.encrypt("BB2210762399,FA7310762361"),
        call.encrypt("theEventToken"),
        call.blind_index("theEventToken"),
        call.execute(
            SQL_INSERT,
            (3, "sealedToken", "theTokenHash", "sealedSecret", "sealedHubs", "sealedEventToken", "theEventHash"),
        ),
    ]
    assert database.mock_calls == exp_calls
    assert token_urlsafe.mock_calls == [call(32)]
    reset_mocks()

    # a second account for one house, which its own settings dialog could not show
    hubs_of.side_effect = [hubs]
    resolve_hubs.side_effect = [["FA7310762361"]]
    database.fetch_one.side_effect = [{"id": 11}]
    with pytest.raises(AppException) as exc_info:
        tested.create_feed(user, payload)
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "This house already collects from a SwitchBot account. Edit that one instead."
    assert database.mock_calls == [call.fetch_one(SQL_EXISTING, (3,))]
    assert token_urlsafe.mock_calls == []
    assert require_admin.mock_calls == [call(user)]
    assert require_house.mock_calls == [call(user, 3)]
    assert resolve_hubs.mock_calls == [call(hubs, payload)]
    assert hubs_of.mock_calls == [call("theToken", "theSecret")]
    reset_mocks()


@patch.object(SwitchBotCommand, "_hubs_of")
@patch.object(SwitchBotCommand, "_resolve_hubs")
@patch.object(SwitchBotCommand, "_require_feed")
@patch.object(SwitchBotCommand, "_require_admin")
def test_update_feed(
    require_admin: MagicMock,
    require_feed: MagicMock,
    resolve_hubs: MagicMock,
    hubs_of: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    hubs = SwitchBotHubs(helper_devices())

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        resolve_hubs.reset_mock()
        hubs_of.reset_mock()
        database.reset_mock()

    user = helper_user()
    feed = {"id": 11, "house_id": 3, "token": "sealedToken", "secret": "sealedSecret", "event_token": "sealedEventToken"}

    # new credentials typed in
    payload: dict[str, Any] = {"token": "newToken", "secret": "newSecret", "hub_ids": ["FA7310762361"], "active": True}
    require_feed.side_effect = [feed]
    hubs_of.side_effect = [hubs]
    resolve_hubs.side_effect = [["FA7310762361"]]
    database.encrypt.side_effect = ["sealedNewToken", "sealedNewSecret", "sealedHubs"]
    database.blind_index.side_effect = ["newTokenHash"]
    database.execute.side_effect = [1]
    result = tested.update_feed(user, 11, payload)
    expected = {"message": "SwitchBot feed updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert resolve_hubs.mock_calls == [call(hubs, payload)]
    assert hubs_of.mock_calls == [call("newToken", "newSecret")]
    exp_calls = [
        call.encrypt("newToken"),
        call.blind_index("newToken"),
        call.encrypt("newSecret"),
        call.encrypt("FA7310762361"),
        call.execute(SQL_UPDATE, ("sealedNewToken", "newTokenHash", "sealedNewSecret", "sealedHubs", True, 11)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # both left empty: the stored pair is kept, which is the ordinary edit
    payload = {"token": "", "secret": "", "hub_ids": ["FA7310762361"], "active": False}
    require_feed.side_effect = [feed]
    database.decrypt.side_effect = ["theToken", "theSecret"]
    hubs_of.side_effect = [hubs]
    resolve_hubs.side_effect = [["FA7310762361"]]
    database.encrypt.side_effect = ["sealedToken", "sealedSecret", "sealedHubs"]
    database.blind_index.side_effect = ["theTokenHash"]
    database.execute.side_effect = [1]
    result = tested.update_feed(user, 11, payload)
    assert result == {"message": "SwitchBot feed updated."}
    assert hubs_of.mock_calls == [call("theToken", "theSecret")]
    exp_calls = [
        call.decrypt("sealedToken"),
        call.decrypt("sealedSecret"),
        call.encrypt("theToken"),
        call.blind_index("theToken"),
        call.encrypt("theSecret"),
        call.encrypt("FA7310762361"),
        call.execute(SQL_UPDATE, ("sealedToken", "theTokenHash", "sealedSecret", "sealedHubs", False, 11)),
    ]
    assert database.mock_calls == exp_calls
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    assert resolve_hubs.mock_calls == [call(hubs, payload)]
    reset_mocks()


@patch.object(SwitchBotCommand, "_unregister")
@patch.object(SwitchBotCommand, "_require_feed")
@patch.object(SwitchBotCommand, "_require_admin")
def test_delete_feed(require_admin: MagicMock, require_feed: MagicMock, unregister: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        require_feed.reset_mock()
        unregister.reset_mock()
        database.reset_mock()

    user = helper_user()
    feed = helper_feed()
    require_feed.side_effect = [feed]
    unregister.side_effect = [None]
    database.execute.side_effect = [1]
    result = tested.delete_feed(user, 11)
    expected = {"message": "SwitchBot feed deleted. The thermometers it collected keep everything they have."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert require_feed.mock_calls == [call(user, 11)]
    # asked to stop posting before the URL it posts to stops answering
    assert unregister.mock_calls == [call(feed)]
    assert database.mock_calls == [call.execute("DELETE FROM switchbot_feeds WHERE id = %s", (11,))]
    reset_mocks()


@patch("usage.commands.switch_bot_command.logging")
@patch("usage.commands.switch_bot_command.SwitchBotClient")
def test__unregister(client_class: MagicMock, mock_logging: MagicMock) -> None:
    client = MagicMock()
    logger = MagicMock()
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        client_class.reset_mock()
        mock_logging.reset_mock()
        client.reset_mock()
        logger.reset_mock()
        database.reset_mock()

    feed = helper_feed()
    url = "https://usage.example.com/api/switchbot/events/theEventToken"

    database.decrypt.side_effect = ["theEventToken", "theToken", "theSecret"]
    client_class.side_effect = [client]
    client.delete_webhook.side_effect = [None]
    result = tested._unregister(feed)
    assert result is None
    assert client_class.mock_calls == [call("theToken", "theSecret", tested._limiter)]
    assert client.mock_calls == [call.delete_webhook(url)]
    exp_calls = [call.decrypt("sealedEventToken"), call.decrypt("sealedToken"), call.decrypt("sealedSecret")]
    assert database.mock_calls == exp_calls
    assert mock_logging.mock_calls == []
    reset_mocks()

    # an account that cannot be reached must not leave the feed half removed
    database.decrypt.side_effect = ["theEventToken", "theToken", "theSecret"]
    client_class.side_effect = [client]
    client.delete_webhook.side_effect = [AppException(502, "SwitchBot could not be reached.")]
    mock_logging.getLogger.side_effect = [logger]
    result = tested._unregister(feed)
    assert result is None
    assert client.mock_calls == [call.delete_webhook(url)]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    exp_calls = [call.info("[SWITCHBOT] webhook not withdrawn: %s", "SwitchBot could not be reached.")]
    assert logger.mock_calls == exp_calls
    assert database.mock_calls == [call.decrypt("sealedEventToken"), call.decrypt("sealedToken"), call.decrypt("sealedSecret")]
    assert client_class.mock_calls == [call("theToken", "theSecret", tested._limiter)]
    reset_mocks()

    # nowhere to withdraw from: the app has no public address, so none was ever set
    tested = helper_instance("http://localhost:8063")
    database = tested._database
    database.decrypt.side_effect = ["theEventToken"]
    result = tested._unregister(feed)
    assert result is None
    assert client_class.mock_calls == []
    assert client.mock_calls == []
    assert database.mock_calls == [call.decrypt("sealedEventToken")]
    assert mock_logging.mock_calls == []
    reset_mocks()


def test__event_url() -> None:
    tested = helper_instance()
    result = tested._event_url("theEventToken")
    expected = "https://usage.example.com/api/switchbot/events/theEventToken"
    assert result == expected

    tests: list[tuple[str, str]] = [
        # no address to be posted to, and http is not one SwitchBot accepts
        ("http://localhost:8063", ""),
        ("", ""),
    ]
    for base_url, expected in tests:
        tested = helper_instance(base_url)
        result = tested._event_url("theEventToken")
        assert result == expected

    # and a feed with no secret yet has no URL either
    tested = helper_instance()
    result = tested._event_url("")
    assert result == ""


@patch.object(SwitchBotCommand, "_hubs_of")
def test__picker(hubs_of: MagicMock) -> None:
    tested = helper_instance()

    def reset_mocks() -> None:
        hubs_of.reset_mock()

    hubs = SwitchBotHubs(helper_devices())
    hubs_of.side_effect = [hubs]
    result = tested._picker("theToken", "theSecret")
    expected = [
        {"hub_id": "BB2210762399", "name": "BB2210762399", "devices": ["Salon"]},
        {"hub_id": "FA7310762361", "name": "Hub Fremur", "devices": ["Grenier", "Dehors"]},
    ]
    assert result == expected
    assert hubs_of.mock_calls == [call("theToken", "theSecret")]
    reset_mocks()


@patch("usage.commands.switch_bot_command.SwitchBotClient")
def test__hubs_of(client_class: MagicMock) -> None:
    client = MagicMock()
    tested = helper_instance()

    def reset_mocks() -> None:
        client_class.reset_mock()
        client.reset_mock()

    devices = helper_devices()

    client_class.side_effect = [client]
    client.devices.side_effect = [devices]
    result = tested._hubs_of("theToken", "theSecret")
    assert isinstance(result, SwitchBotHubs)
    assert result.following(("FA7310762361",)) == [devices[0], devices[1], devices[2]]
    assert client_class.mock_calls == [call("theToken", "theSecret", tested._limiter)]
    assert client.mock_calls == [call.devices()]
    reset_mocks()

    # credentials that work on an account holding nothing at all
    client_class.side_effect = [client]
    client.devices.side_effect = [[]]
    with pytest.raises(AppException) as exc_info:
        tested._hubs_of("theToken", "theSecret")
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "That SwitchBot account has no device on it."
    assert client_class.mock_calls == [call("theToken", "theSecret", tested._limiter)]
    assert client.mock_calls == [call.devices()]
    reset_mocks()


def test__resolve_hubs() -> None:
    tested = helper_instance()
    hubs = SwitchBotHubs(helper_devices())

    # deduplicated and ordered, so the same choice always stores the same thing
    result = tested._resolve_hubs(hubs, {"hub_ids": ["FA7310762361", " BB2210762399 ", "FA7310762361"]})
    expected = ["BB2210762399", "FA7310762361"]
    assert result == expected

    tests: list[tuple[dict[str, Any], str]] = [
        ({}, "Choose at least one hub: its devices are what this house collects."),
        ({"hub_ids": ["  "]}, "Choose at least one hub: its devices are what this house collects."),
        ({"hub_ids": ["FA7310762361", "CC9999999999"]}, "This account has nothing behind CC9999999999 any more."),
    ]
    for data, message in tests:
        with pytest.raises(AppException) as exc_info:
            tested._resolve_hubs(hubs, data)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == message


def test__credentials() -> None:
    tested = helper_instance()

    result = tested._credentials({"token": " theToken ", "secret": " theSecret "})
    expected = ("theToken", "theSecret")
    assert result == expected

    for data in ({"secret": "theSecret"}, {"token": "theToken"}, {}):
        with pytest.raises(AppException) as exc_info:
            tested._credentials(data)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "Enter the SwitchBot token and secret, both from the app's Developer Options."


def test__split() -> None:
    tested = helper_instance()
    tests: list[tuple[str, tuple[str, ...]]] = [
        ("BB2210762399,FA7310762361", ("BB2210762399", "FA7310762361")),
        ("FA7310762361", ("FA7310762361",)),
        ("", ()),
    ]
    for sealed, expected in tests:
        result = tested._split(sealed)
        assert result == expected


def test__moment() -> None:
    tested = helper_instance()
    tests: list[tuple[datetime | None, str]] = [
        (datetime(2026, 9, 17, 14, 2, tzinfo=UTC), "2026-09-17T14:02:00+00:00"),
        (None, ""),
    ]
    for value, expected in tests:
        result = tested._moment(value)
        assert result == expected


def test__visible_house_ids() -> None:
    tested = helper_instance()
    database = tested._database

    database.fetch_all.side_effect = [[{"house_id": 3}, {"house_id": 5}]]
    result = tested._visible_house_ids(helper_user())
    expected = [3, 5]
    assert result == expected
    exp_calls = [call.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (7,))]
    assert database.mock_calls == exp_calls


def test__require_admin() -> None:
    tested = helper_instance()

    result = tested._require_admin(helper_user())
    assert result is None

    with pytest.raises(AppException) as exc_info:
        tested._require_admin(helper_user(is_admin=False))
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Only admins can do this."


@patch.object(SwitchBotCommand, "_visible_house_ids")
def test__require_house(visible: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_database = [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]

    database.fetch_one.side_effect = [{"id": 3}]
    visible.side_effect = [[3, 5]]
    result = tested._require_house(user, 3)
    assert result is None
    assert visible.mock_calls == [call(user)]
    assert database.mock_calls == exp_database
    reset_mocks()

    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert visible.mock_calls == []
    assert database.mock_calls == exp_database
    reset_mocks()

    database.fetch_one.side_effect = [{"id": 3}]
    visible.side_effect = [[5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 3)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible.mock_calls == [call(user)]
    assert database.mock_calls == exp_database
    reset_mocks()


@patch.object(SwitchBotCommand, "_visible_house_ids")
def test__require_feed(visible: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible.reset_mock()
        database.reset_mock()

    user = helper_user()
    feed = {"id": 11, "house_id": 3, "token": "sealedToken", "secret": "sealedSecret", "event_token": "sealedEventToken"}
    exp_database = [call.fetch_one(SQL_FEED, (11,))]

    database.fetch_one.side_effect = [feed]
    visible.side_effect = [[3, 5]]
    result = tested._require_feed(user, 11)
    assert result == feed
    assert visible.mock_calls == [call(user)]
    assert database.mock_calls == exp_database
    reset_mocks()

    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_feed(user, 11)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The SwitchBot feed was not found."
    assert visible.mock_calls == []
    assert database.mock_calls == exp_database
    reset_mocks()

    database.fetch_one.side_effect = [feed]
    visible.side_effect = [[5]]
    with pytest.raises(AppException) as exc_info:
        tested._require_feed(user, 11)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible.mock_calls == [call(user)]
    assert database.mock_calls == exp_database
    reset_mocks()
