from __future__ import annotations

import urllib.error
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.libraries.switch_bot_client import SwitchBotClient
from usage.structures.app_exception import AppException
from usage.structures.switch_bot_device import SwitchBotDevice
from usage.structures.switch_bot_reading import SwitchBotReading


def helper_instance(limiter: MagicMock | None = None) -> SwitchBotClient:
    return SwitchBotClient("theToken", "theSecret", limiter)


def test___init__() -> None:
    tested = helper_instance()
    assert tested._token == "theToken"
    assert tested._secret == "theSecret"
    assert tested._limiter is None

    limiter = MagicMock()
    tested = helper_instance(limiter)
    assert tested._limiter is limiter
    assert limiter.mock_calls == []


@patch.object(SwitchBotClient, "_get")
def test_devices(get: MagicMock) -> None:
    def reset_mocks() -> None:
        get.reset_mock()

    tested = helper_instance()

    get.side_effect = [
        {
            "deviceList": [
                {"deviceId": "C271111EC0AB", "deviceName": "Grenier", "deviceType": "Meter", "hubDeviceId": "FA7310762361"},
                # a hub names no hub of its own, and a device with none names
                # twelve zeros: both are nothing, and are placed further up
                {"deviceId": "FA7310762361", "deviceName": "Hub Fremur", "deviceType": "Hub 2", "hubDeviceId": ""},
                {"deviceId": "D382222FD1BC", "deviceName": "Freezer", "deviceType": "Meter", "hubDeviceId": "000000000000"},
                # nothing usable: no id at all, and a stray entry that is not an object
                {"deviceName": "Nameless"},
                "not-a-device",
            ],
        },
    ]
    result = tested.devices()
    expected = [
        SwitchBotDevice(device_id="C271111EC0AB", name="Grenier", device_type="Meter", hub_id="FA7310762361"),
        SwitchBotDevice(device_id="FA7310762361", name="Hub Fremur", device_type="Hub 2", hub_id=""),
        SwitchBotDevice(device_id="D382222FD1BC", name="Freezer", device_type="Meter", hub_id=""),
    ]
    assert result == expected
    assert get.mock_calls == [call("/v1.1/devices")]
    reset_mocks()

    # an account with nothing on it
    get.side_effect = [{}]
    result = tested.devices()
    assert result == []
    assert get.mock_calls == [call("/v1.1/devices")]
    reset_mocks()


@patch.object(SwitchBotClient, "_get")
def test_status(get: MagicMock) -> None:
    def reset_mocks() -> None:
        get.reset_mock()

    tested = helper_instance()

    get.side_effect = [{"temperature": 26.1, "humidity": 52, "battery": 86.7}]
    result = tested.status("C271111EC0AB")
    expected = SwitchBotReading(device_id="C271111EC0AB", temperature=26.1, humidity=52.0, battery=87)
    assert result == expected
    assert get.mock_calls == [call("/v1.1/devices/C271111EC0AB/status")]
    reset_mocks()

    # a thermometer whose charge the status does not carry
    get.side_effect = [{"temperature": 19.4, "humidity": 61}]
    result = tested.status("C271111EC0AB")
    expected = SwitchBotReading(device_id="C271111EC0AB", temperature=19.4, humidity=61.0, battery=None)
    assert result == expected
    assert get.mock_calls == [call("/v1.1/devices/C271111EC0AB/status")]
    reset_mocks()

    # a device that is no thermometer: it is not asked what it is, only what it reads
    get.side_effect = [{"power": "on"}]
    result = tested.status("C271111EC0AB")
    assert result is None
    assert get.mock_calls == [call("/v1.1/devices/C271111EC0AB/status")]
    reset_mocks()


@patch.object(SwitchBotClient, "_fetch")
def test__get(fetch: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch.reset_mock()

    tested = helper_instance()

    fetch.side_effect = ['{"statusCode": 100, "body": {"temperature": 26.1}, "message": "success"}']
    result = tested._get("/v1.1/devices/C271111EC0AB/status")
    expected = {"temperature": 26.1}
    assert result == expected
    assert fetch.mock_calls == [call("https://api.switch-bot.com/v1.1/devices/C271111EC0AB/status")]
    reset_mocks()

    # a success whose body is not an object
    fetch.side_effect = ['{"statusCode": 100, "body": [], "message": "success"}']
    result = tested._get("/v1.1/devices")
    assert result == {}
    assert fetch.mock_calls == [call("https://api.switch-bot.com/v1.1/devices")]
    reset_mocks()

    # a refusal, which arrives as a 200 with the verdict in the body
    tests: list[tuple[str, str]] = [
        (
            '{"statusCode": 161, "message": "device offline"}',
            "SwitchBot refused the request: device offline",
        ),
        ('{"statusCode": 190}', "SwitchBot refused the request (code 190)."),
        ("not json at all", "SwitchBot refused the request (code None)."),
    ]
    for raw, message in tests:
        fetch.side_effect = [raw]
        with pytest.raises(AppException) as exc_info:
            tested._get("/v1.1/devices")
        assert exc_info.value.status_code == 422
        assert exc_info.value.message == message
        assert fetch.mock_calls == [call("https://api.switch-bot.com/v1.1/devices")]
        reset_mocks()


@patch.object(SwitchBotClient, "_fetch")
def test_setup_webhook(fetch: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch.reset_mock()

    tested = helper_instance()
    fetch.side_effect = ['{"statusCode": 100, "body": {}, "message": "success"}']
    result = tested.setup_webhook("https://usage.example.com/api/switchbot/events/theEventToken")
    assert result is None
    exp_calls = [
        call(
            "https://api.switch-bot.com/v1.1/webhook/setupWebhook",
            b'{"action": "setupWebhook", "url": "https://usage.example.com/api/switchbot/events/theEventToken", "deviceList": "ALL"}',
        ),
    ]
    assert fetch.mock_calls == exp_calls
    reset_mocks()


@patch.object(SwitchBotClient, "_fetch")
def test_delete_webhook(fetch: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch.reset_mock()

    tested = helper_instance()
    fetch.side_effect = ['{"statusCode": 100, "body": {}, "message": "success"}']
    result = tested.delete_webhook("https://usage.example.com/api/switchbot/events/theEventToken")
    assert result is None
    exp_calls = [
        call(
            "https://api.switch-bot.com/v1.1/webhook/deleteWebhook",
            b'{"action": "deleteWebhook", "url": "https://usage.example.com/api/switchbot/events/theEventToken"}',
        ),
    ]
    assert fetch.mock_calls == exp_calls
    reset_mocks()


@patch.object(SwitchBotClient, "_fetch")
def test__post(fetch: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch.reset_mock()

    tested = helper_instance()

    fetch.side_effect = ['{"statusCode": 100, "body": {}, "message": "success"}']
    result = tested._post("/v1.1/webhook/setupWebhook", {"action": "setupWebhook"})
    expected = {"statusCode": 100, "body": {}, "message": "success"}
    assert result == expected
    exp_calls = [call("https://api.switch-bot.com/v1.1/webhook/setupWebhook", b'{"action": "setupWebhook"}')]
    assert fetch.mock_calls == exp_calls
    reset_mocks()

    # a refusal arrives as a 200 here too
    fetch.side_effect = ['{"statusCode": 190, "message": "wrong parameter"}']
    with pytest.raises(AppException) as exc_info:
        tested._post("/v1.1/webhook/setupWebhook", {"action": "setupWebhook"})
    assert exc_info.value.status_code == 422
    assert exc_info.value.message == "SwitchBot refused the request: wrong parameter"
    assert fetch.mock_calls == exp_calls
    reset_mocks()


@patch.object(SwitchBotClient, "_headers")
@patch.object(SwitchBotClient, "_await_slot")
@patch("usage.libraries.switch_bot_client.urllib.request.urlopen")
@patch("usage.libraries.switch_bot_client.urllib.request.Request")
def test__fetch(request_class: MagicMock, urlopen: MagicMock, await_slot: MagicMock, headers: MagicMock) -> None:
    request = MagicMock()
    response = MagicMock()

    def reset_mocks() -> None:
        request_class.reset_mock()
        urlopen.reset_mock()
        await_slot.reset_mock()
        headers.reset_mock()
        request.reset_mock()
        response.reset_mock()

    tested = helper_instance()
    exp_request = call("https://api.switch-bot.com/v1.1/devices", data=None, headers={"sign": "theSign"})

    headers.side_effect = [{"sign": "theSign"}]
    request_class.side_effect = [request]
    urlopen.return_value.__enter__.side_effect = [response]
    response.read.side_effect = [b"theBody"]
    result = tested._fetch("https://api.switch-bot.com/v1.1/devices")
    expected = "theBody"
    assert result == expected
    assert request_class.mock_calls == [exp_request]
    exp_calls = [call(request, timeout=30), call().__enter__(), call().__exit__(None, None, None)]
    assert urlopen.mock_calls == exp_calls
    assert request.mock_calls == []
    assert response.mock_calls == [call.read()]
    # no request leaves without a slot under the day's allowance
    assert await_slot.mock_calls == [call()]
    assert headers.mock_calls == [call()]
    reset_mocks()

    tests: list[tuple[Exception, int, str]] = [
        (urllib.error.HTTPError("https://api.switch-bot.com", 429, "Too Many", {}, None), 429, "SwitchBot is refusing more requests for now."),  # type: ignore[arg-type]
        (urllib.error.URLError("no route"), 502, "SwitchBot could not be reached."),
        (OSError("socket died"), 502, "SwitchBot could not be reached."),
    ]
    for error, status_code, message in tests:
        headers.side_effect = [{"sign": "theSign"}]
        request_class.side_effect = [request]
        urlopen.side_effect = [error]
        with pytest.raises(AppException) as exc_info:
            tested._fetch("https://api.switch-bot.com/v1.1/devices")
        assert exc_info.value.status_code == status_code
        assert exc_info.value.message == message
        assert request_class.mock_calls == [exp_request]
        assert urlopen.mock_calls == [call(request, timeout=30)]
        assert request.mock_calls == []
        assert response.mock_calls == []
        assert await_slot.mock_calls == [call()]
        assert headers.mock_calls == [call()]
        reset_mocks()


@patch("usage.libraries.switch_bot_client.uuid")
@patch("usage.libraries.switch_bot_client.time")
def test__headers(mock_time: MagicMock, mock_uuid: MagicMock) -> None:
    def reset_mocks() -> None:
        mock_time.reset_mock()
        mock_uuid.reset_mock()

    tested = helper_instance()
    mock_time.time.side_effect = [1_789_000_000.123]
    mock_uuid.uuid4.side_effect = ["1d3f0b1c-0000-4000-8000-000000000001"]
    result = tested._headers()
    expected = {
        "Authorization": "theToken",
        "Content-Type": "application/json",
        "charset": "utf8",
        "t": "1789000000123",
        # their own Python sample's signature, which is not upper-cased
        "sign": "tajXUSDj/YIkUpJLB4aTU8a2Lbrshs/BY50BRc4xF7I=",
        "nonce": "1d3f0b1c-0000-4000-8000-000000000001",
    }
    assert result == expected
    assert mock_time.mock_calls == [call.time()]
    assert mock_uuid.mock_calls == [call.uuid4()]
    reset_mocks()


def test__await_slot() -> None:
    limiter = MagicMock()

    def reset_mocks() -> None:
        limiter.reset_mock()

    # no limiter at all, as when a test or a probe drives the client directly
    tested = helper_instance()
    result = tested._await_slot()
    assert result is None
    assert limiter.mock_calls == []
    reset_mocks()

    tested = helper_instance(limiter)
    limiter.acquire.side_effect = [True]
    result = tested._await_slot()
    assert result is None
    assert limiter.mock_calls == [call.acquire("theToken", 0.0)]
    reset_mocks()

    # the day is spent: nobody waits it out, so the tick says so and is tried again
    limiter.acquire.side_effect = [False]
    with pytest.raises(AppException) as exc_info:
        tested._await_slot()
    assert exc_info.value.status_code == 429
    assert exc_info.value.message == "SwitchBot has been asked as many times as the day's allowance permits."
    assert limiter.mock_calls == [call.acquire("theToken", 0.0)]
    reset_mocks()


def test__refusal() -> None:
    tested = helper_instance()
    tests: list[tuple[dict[str, Any], str]] = [
        ({"statusCode": 161, "message": "device offline"}, "SwitchBot refused the request: device offline"),
        ({"statusCode": 190, "message": "   "}, "SwitchBot refused the request (code 190)."),
        ({}, "SwitchBot refused the request (code None)."),
        ({"statusCode": 190, "message": "x" * 400}, f"SwitchBot refused the request: {'x' * 300}"),
    ]
    for payload, expected in tests:
        result = tested._refusal(payload)
        assert result == expected


def test__http_failure() -> None:
    tested = helper_instance()
    tests: list[tuple[int, int, str]] = [
        (401, 401, "SwitchBot refused the token and secret. Both are copied from the app, Profile, Preferences, Developer Options."),
        (403, 401, "SwitchBot refused the token and secret. Both are copied from the app, Profile, Preferences, Developer Options."),
        (429, 429, "SwitchBot is refusing more requests for now."),
        (500, 502, "SwitchBot could not be reached."),
    ]
    for code, status_code, message in tests:
        error = urllib.error.HTTPError("https://api.switch-bot.com", code, "Boom", {}, None)  # type: ignore[arg-type]
        result = tested._http_failure(error)
        assert result.status_code == status_code
        assert result.message == message


def test__json() -> None:
    tested = helper_instance()
    tests: list[tuple[str, dict[str, Any]]] = [
        ('{"statusCode": 100}', {"statusCode": 100}),
        ("[1, 2]", {}),
        ("not json", {}),
    ]
    for raw, expected in tests:
        result = tested._json(raw)
        assert result == expected


def test__hub_id() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, str]] = [
        ("FA7310762361", "FA7310762361"),
        ("  FA7310762361  ", "FA7310762361"),
        # the two ways a device says it has no hub, which are one thing here
        ("000000000000", ""),
        ("", ""),
        (None, ""),
    ]
    for raw, expected in tests:
        result = tested._hub_id(raw)
        assert result == expected


def test__number() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, float | None]] = [
        (26.1, 26.1),
        ("26.1", 26.1),
        (0, 0.0),
        (None, None),
        (True, None),
        ("warm", None),
        ([], None),
    ]
    for raw, expected in tests:
        result = tested._number(raw)
        assert result == expected
