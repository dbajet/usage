from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.libraries.enphase_client import EnphaseClient
from usage.structures.app_exception import AppException
from usage.structures.enphase_point import EnphasePoint
from usage.structures.enphase_system import EnphaseSystem
from usage.structures.enphase_tokens import EnphaseTokens

NOW = datetime(2026, 9, 16, 7, 14, tzinfo=UTC)


def helper_tokens(expires_at: datetime | None = None) -> EnphaseTokens:
    return EnphaseTokens(access_token="theAccessToken", refresh_token="theRefreshToken", expires_at=expires_at)


def helper_instance(tokens: EnphaseTokens | None = None, limiter: MagicMock | None = None) -> EnphaseClient:
    return EnphaseClient("theClientId", "theClientSecret", "theApiKey", tokens or helper_tokens(), limiter)


def test___init__() -> None:
    tokens = helper_tokens()
    tested = helper_instance(tokens)
    assert tested._client_id == "theClientId"
    assert tested._client_secret == "theClientSecret"
    assert tested._api_key == "theApiKey"
    assert tested._tokens == tokens
    assert tested._calls == 0

    assert tested._limiter is None

    limiter = MagicMock()
    tested = helper_instance(tokens, limiter)
    assert tested._limiter is limiter
    assert limiter.mock_calls == []

    tested = EnphaseClient("theClientId", "theClientSecret", "theApiKey")
    assert tested._tokens == EnphaseTokens(access_token="", refresh_token="", expires_at=None)
    assert tested._limiter is None


def test_tokens() -> None:
    tokens = helper_tokens()
    tested = helper_instance(tokens)
    result = tested.tokens
    assert result == tokens


def test_calls() -> None:
    tested = helper_instance()
    result = tested.calls
    assert result == 0

    tested._calls = 7
    result = tested.calls
    assert result == 7


def test_authorize_url() -> None:
    tested = EnphaseClient
    result = tested.authorize_url("theClientId")
    expected = (
        "https://api.enphaseenergy.com/oauth/authorize?response_type=code&client_id=theClientId"
        "&redirect_uri=https%3A%2F%2Fapi.enphaseenergy.com%2Foauth%2Fredirect_uri"
    )
    assert result == expected


@patch.object(EnphaseClient, "_store")
@patch.object(EnphaseClient, "_token_call")
def test_exchange(token_call: MagicMock, store: MagicMock) -> None:
    def reset_mocks() -> None:
        token_call.reset_mock()
        store.reset_mock()

    tokens = helper_tokens()
    token_call.side_effect = [{"access_token": "theAccessToken"}]
    store.side_effect = [tokens]
    tested = helper_instance()
    result = tested.exchange("theCode")
    assert result == tokens
    exp_calls = [
        call(
            {
                "grant_type": "authorization_code",
                "redirect_uri": "https://api.enphaseenergy.com/oauth/redirect_uri",
                "code": "theCode",
            },
            "Enphase refused that authorisation code. They expire within minutes, so it may simply be stale.",
        ),
    ]
    assert token_call.mock_calls == exp_calls
    assert store.mock_calls == [call({"access_token": "theAccessToken"})]
    reset_mocks()


@patch.object(EnphaseClient, "_store")
@patch.object(EnphaseClient, "_token_call")
def test_refresh(token_call: MagicMock, store: MagicMock) -> None:
    def reset_mocks() -> None:
        token_call.reset_mock()
        store.reset_mock()

    tokens = helper_tokens()
    token_call.side_effect = [{"access_token": "theAccessToken"}]
    store.side_effect = [tokens]
    tested = helper_instance()
    result = tested.refresh()
    assert result == tokens
    exp_calls = [
        call(
            {"grant_type": "refresh_token", "refresh_token": "theRefreshToken"},
            "Enphase refused the stored authorisation. A refresh token lasts about a month, "
            "so a feed left paused for longer has to be authorised again.",
        ),
    ]
    assert token_call.mock_calls == exp_calls
    assert store.mock_calls == [call({"access_token": "theAccessToken"})]
    reset_mocks()

    # a feed that was never authorised has nothing to refresh
    tested = helper_instance(EnphaseTokens(access_token="theAccessToken", refresh_token=""))
    with pytest.raises(AppException) as exc_info:
        tested.refresh()
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "This Enphase feed has never been authorised."
    assert token_call.mock_calls == []
    assert store.mock_calls == []
    reset_mocks()


@patch.object(EnphaseClient, "_get")
def test_systems(get: MagicMock) -> None:
    def reset_mocks() -> None:
        get.reset_mock()

    exp_get = call("/api/v4/systems", {"size": 100})

    # a system named by `system_id`, one by the bare `id`, and two that carry neither
    payload = {
        "systems": [
            {"system_id": 3456789, "name": "Dougmar", "status": "normal"},
            {"id": 987654},
            {"name": "no id at all"},
            "notASystem",
        ],
    }
    get.side_effect = [payload]
    tested = helper_instance()
    result = tested.systems()
    expected = [
        EnphaseSystem(system_id="3456789", name="Dougmar", status="normal"),
        EnphaseSystem(system_id="987654", name="", status=""),
    ]
    assert result == expected
    assert get.mock_calls == [exp_get]
    reset_mocks()

    # every shape the answer can take without carrying a system
    for payload in [{}, {"systems": []}, {"systems": None}]:
        get.side_effect = [payload]
        tested = helper_instance()
        result = tested.systems()
        assert result == []
        assert get.mock_calls == [exp_get]
        reset_mocks()


@patch.object(EnphaseClient, "_telemetry")
def test_production(telemetry: MagicMock) -> None:
    def reset_mocks() -> None:
        telemetry.reset_mock()

    points = [EnphasePoint(measured_at=NOW, production=0.4)]
    exp_meter = call(
        "/api/v4/systems/{system_id}/telemetry/production_meter",
        "3456789",
        date(2026, 9, 16),
        "production",
    )
    exp_micro = call(
        "/api/v4/systems/{system_id}/telemetry/production_micro",
        "3456789",
        date(2026, 9, 16),
        "production",
    )

    # a system with production CTs is answered by the meter
    telemetry.side_effect = [points]
    tested = helper_instance()
    result = tested.production("3456789", date(2026, 9, 16))
    assert result == points
    assert telemetry.mock_calls == [exp_meter]
    reset_mocks()

    # an empty day is a good answer at night, not a reason to ask twice
    telemetry.side_effect = [[]]
    tested = helper_instance()
    result = tested.production("3456789", date(2026, 9, 16))
    assert result == []
    assert telemetry.mock_calls == [exp_meter]
    reset_mocks()

    # a system with no production meter refuses that endpoint: the inverters answer
    telemetry.side_effect = [AppException(422, "no production meter"), points]
    tested = helper_instance()
    result = tested.production("3456789", date(2026, 9, 16))
    assert result == points
    assert telemetry.mock_calls == [exp_meter, exp_micro]
    reset_mocks()

    # a refusal or an outage is not a verdict on the endpoint
    telemetry.side_effect = [AppException(401, "theRefusal")]
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested.production("3456789", date(2026, 9, 16))
    assert exc_info.value.status_code == 401
    assert telemetry.mock_calls == [exp_meter]
    reset_mocks()


@patch.object(EnphaseClient, "_telemetry")
def test_consumption(telemetry: MagicMock) -> None:
    def reset_mocks() -> None:
        telemetry.reset_mock()

    points = [EnphasePoint(measured_at=NOW, consumption=0.2)]
    telemetry.side_effect = [points]
    tested = helper_instance()
    result = tested.consumption("3456789", date(2026, 9, 16))
    assert result == points
    exp_calls = [
        call(
            "/api/v4/systems/{system_id}/telemetry/consumption_meter",
            "3456789",
            date(2026, 9, 16),
            "consumption",
        ),
    ]
    assert telemetry.mock_calls == exp_calls
    reset_mocks()


@patch.object(EnphaseClient, "_telemetry")
def test_battery(telemetry: MagicMock) -> None:
    def reset_mocks() -> None:
        telemetry.reset_mock()

    points = [EnphasePoint(measured_at=NOW, battery_level=87.5)]
    telemetry.side_effect = [points]
    tested = helper_instance()
    result = tested.battery("3456789", date(2026, 9, 16))
    assert result == points
    exp_calls = [
        call("/api/v4/systems/{system_id}/telemetry/battery", "3456789", date(2026, 9, 16), "battery"),
    ]
    assert telemetry.mock_calls == exp_calls
    reset_mocks()


@patch.object(EnphaseClient, "_lifetime")
def test_daily(lifetime: MagicMock) -> None:
    def reset_mocks() -> None:
        lifetime.reset_mock()

    first = datetime(2026, 9, 15, tzinfo=UTC)
    second = datetime(2026, 9, 16, tzinfo=UTC)
    # the same day arrives from both endpoints and must end up as one row
    produced = [
        EnphasePoint(measured_at=first, span_minutes=1440, production=12.0),
        EnphasePoint(measured_at=second, span_minutes=1440, production=14.0),
    ]
    consumed = [
        EnphasePoint(measured_at=second, span_minutes=1440, consumption=21.0),
        EnphasePoint(measured_at=first, span_minutes=1440, consumption=19.0),
    ]
    lifetime.side_effect = [produced, consumed]
    tested = helper_instance()
    result = tested.daily("3456789", date(2026, 9, 15), date(2026, 9, 16))
    expected = [
        EnphasePoint(measured_at=first, span_minutes=1440, production=12.0, consumption=19.0),
        EnphasePoint(measured_at=second, span_minutes=1440, production=14.0, consumption=21.0),
    ]
    assert result == expected
    exp_calls = [
        call(
            "/api/v4/systems/{system_id}/energy_lifetime",
            "3456789",
            date(2026, 9, 15),
            date(2026, 9, 16),
            "production",
        ),
        call(
            "/api/v4/systems/{system_id}/consumption_lifetime",
            "3456789",
            date(2026, 9, 15),
            date(2026, 9, 16),
            "consumption",
        ),
    ]
    assert lifetime.mock_calls == exp_calls
    reset_mocks()


@patch.object(EnphaseClient, "_get")
def test__lifetime(get: MagicMock) -> None:
    def reset_mocks() -> None:
        get.reset_mock()

    exp_get = call(
        "/api/v4/systems/3456789/energy_lifetime",
        {"start_date": "2026-09-14", "end_date": "2026-09-16"},
    )

    # the index of an element is its day, counted from the date the answer names
    get.side_effect = [{"start_date": "2026-09-14", "production": [12000, "13500", None, 14000]}]
    tested = helper_instance()
    result = tested._lifetime(
        "/api/v4/systems/{system_id}/energy_lifetime",
        "3456789",
        date(2026, 9, 14),
        date(2026, 9, 16),
        "production",
    )
    expected = [
        EnphasePoint(measured_at=datetime(2026, 9, 14, tzinfo=UTC), span_minutes=1440, production=12.0),
        EnphasePoint(measured_at=datetime(2026, 9, 15, tzinfo=UTC), span_minutes=1440, production=13.5),
        EnphasePoint(measured_at=datetime(2026, 9, 17, tzinfo=UTC), span_minutes=1440, production=14.0),
    ]
    assert result == expected
    assert get.mock_calls == [exp_get]
    reset_mocks()

    # consumption fills the other column
    get.side_effect = [{"start_date": "2026-09-14", "consumption": [21000]}]
    tested = helper_instance()
    result = tested._lifetime(
        "/api/v4/systems/{system_id}/consumption_lifetime",
        "3456789",
        date(2026, 9, 14),
        date(2026, 9, 16),
        "consumption",
    )
    expected = [
        EnphasePoint(measured_at=datetime(2026, 9, 14, tzinfo=UTC), span_minutes=1440, consumption=21.0),
    ]
    assert result == expected
    exp_calls = [
        call(
            "/api/v4/systems/3456789/consumption_lifetime",
            {"start_date": "2026-09-14", "end_date": "2026-09-16"},
        ),
    ]
    assert get.mock_calls == exp_calls
    reset_mocks()

    # no start at all: the whole life of the system, and no date parameters
    get.side_effect = [{"start_date": "2026-09-14", "production": [12000]}]
    tested = helper_instance()
    result = tested._lifetime("/api/v4/systems/{system_id}/energy_lifetime", "3456789", None, None, "production")
    expected = [
        EnphasePoint(measured_at=datetime(2026, 9, 14, tzinfo=UTC), span_minutes=1440, production=12.0),
    ]
    assert result == expected
    assert get.mock_calls == [call("/api/v4/systems/3456789/energy_lifetime", {})]
    reset_mocks()

    # the field is missing, or is not a list at all
    for payload in [{}, {"production": "nope"}]:
        get.side_effect = [payload]
        tested = helper_instance()
        result = tested._lifetime(
            "/api/v4/systems/{system_id}/energy_lifetime",
            "3456789",
            date(2026, 9, 14),
            date(2026, 9, 16),
            "production",
        )
        assert result == []
        assert get.mock_calls == [exp_get]
        reset_mocks()

    # a list with no date to count from means nothing: better no rows than wrong ones
    get.side_effect = [{"production": [12000]}]
    tested = helper_instance()
    result = tested._lifetime("/api/v4/systems/{system_id}/energy_lifetime", "3456789", None, None, "production")
    assert result == []
    assert get.mock_calls == [call("/api/v4/systems/3456789/energy_lifetime", {})]
    reset_mocks()


@patch.object(EnphaseClient, "_get")
def test__telemetry(get: MagicMock) -> None:
    def reset_mocks() -> None:
        get.reset_mock()

    # midnight UTC on 2026-09-16
    exp_get = call(
        "/api/v4/systems/3456789/telemetry/production_meter",
        {"start_at": 1789516800, "granularity": "day"},
    )

    # an interval is labelled by its start: Enphase reports the far end
    payload = {
        "intervals": [
            {"end_at": 1789517700, "enwh": 412},
            {"end_at": 1789518600, "enwh": 508},
            {"end_at": 1789519500},
            "notAnInterval",
            {"enwh": 100},
        ],
    }
    get.side_effect = [payload]
    tested = helper_instance()
    result = tested._telemetry(
        "/api/v4/systems/{system_id}/telemetry/production_meter",
        "3456789",
        date(2026, 9, 16),
        "production",
    )
    expected = [
        EnphasePoint(measured_at=datetime(2026, 9, 16, 0, 0, tzinfo=UTC), span_minutes=15, production=0.412),
        EnphasePoint(measured_at=datetime(2026, 9, 16, 0, 15, tzinfo=UTC), span_minutes=15, production=0.508),
    ]
    assert result == expected
    assert get.mock_calls == [exp_get]
    reset_mocks()

    # no intervals, or something that is not a list
    for payload in [{}, {"intervals": "nope"}]:
        get.side_effect = [payload]
        tested = helper_instance()
        result = tested._telemetry(
            "/api/v4/systems/{system_id}/telemetry/production_meter",
            "3456789",
            date(2026, 9, 16),
            "production",
        )
        assert result == []
        assert get.mock_calls == [exp_get]
        reset_mocks()


def test__value() -> None:
    tested = helper_instance()
    moment = datetime(2026, 9, 16, 7, 15, tzinfo=UTC)
    tests: list[tuple[dict[str, Any], str, EnphasePoint | None]] = [
        (
            {"enwh": 412},
            "production",
            EnphasePoint(measured_at=moment, span_minutes=15, production=0.412),
        ),
        (
            {"enwh": 412},
            "consumption",
            EnphasePoint(measured_at=moment, span_minutes=15, consumption=0.412),
        ),
        (
            {"soc": {"percent": 87}},
            "battery",
            EnphasePoint(measured_at=moment, span_minutes=15, battery_level=87.0),
        ),
        # an interval carrying nothing this stream can read is no reading at all
        ({}, "production", None),
        ({}, "battery", None),
    ]
    for interval, field, expected in tests:
        result = tested._value(interval, field, moment, 15)
        assert result == expected


def test__percent() -> None:
    tested = helper_instance()
    tests: list[tuple[dict[str, Any], float | None]] = [
        ({"soc": {"percent": 87.456}}, 87.46),
        ({"soc": {"value": 42}}, 42.0),
        ({"soc": 55}, 55.0),
        ({"percent": 61}, 61.0),
        ({"soc_percent": 12}, 12.0),
        ({"state_of_charge": 9}, 9.0),
        # a charge outside the scale is clamped rather than drawn off the graph
        ({"soc": 140}, 100.0),
        ({"soc": -3}, 0.0),
        # a system with no battery answers with none of these
        ({}, None),
        ({"soc": {}}, None),
        ({"soc": "nope"}, None),
    ]
    for interval, expected in tests:
        result = tested._percent(interval)
        assert result == expected


def test__span() -> None:
    tested = helper_instance()
    tests: list[tuple[list[Any], int]] = [
        # quarter-hourly meter telemetry
        ([{"end_at": 1789517700}, {"end_at": 1789518600}, {"end_at": 1789519500}], 15),
        # five-minute microinverter telemetry, through the very same shape
        ([{"end_at": 1789517700}, {"end_at": 1789518000}], 5),
        # out of order, and with a gap: the smallest positive step is the resolution
        ([{"end_at": 1789519500}, {"end_at": 1789517700}, {"end_at": 1789518600}], 15),
        # nothing to measure a gap from
        ([], 15),
        ([{"end_at": 1789517700}], 15),
        ([{"end_at": 1789517700}, {"end_at": 1789517700}], 15),
        (["notAnInterval", {"nope": 1}], 15),
    ]
    for intervals, expected in tests:
        result = tested._span(intervals)
        assert result == expected


@patch.object(EnphaseClient, "_json_or_fail")
@patch.object(EnphaseClient, "_fetch")
@patch.object(EnphaseClient, "_url")
@patch.object(EnphaseClient, "refresh")
@patch.object(EnphaseClient, "_stale")
def test__get(stale: MagicMock, refresh: MagicMock, url: MagicMock, fetch: MagicMock, json_or_fail: MagicMock) -> None:
    def reset_mocks() -> None:
        stale.reset_mock()
        refresh.reset_mock()
        url.reset_mock()
        fetch.reset_mock()
        json_or_fail.reset_mock()

    exp_url = call("/api/v4/systems", {"size": 100})

    # the token is still good
    stale.side_effect = [False]
    url.side_effect = ["https://api.enphaseenergy.com/api/v4/systems?size=100&key=theApiKey"]
    fetch.side_effect = ["theBody"]
    json_or_fail.side_effect = [{"systems": []}]
    tested = helper_instance()
    result = tested._get("/api/v4/systems", {"size": 100})
    assert result == {"systems": []}
    assert stale.mock_calls == [call()]
    assert refresh.mock_calls == []
    assert url.mock_calls == [exp_url]
    assert fetch.mock_calls == [call("https://api.enphaseenergy.com/api/v4/systems?size=100&key=theApiKey")]
    assert json_or_fail.mock_calls == [call("theBody")]
    reset_mocks()

    # the token has expired on the clock: refreshed before the call, not after it
    stale.side_effect = [True]
    refresh.side_effect = [helper_tokens()]
    url.side_effect = ["theUrl"]
    fetch.side_effect = ["theBody"]
    json_or_fail.side_effect = [{"systems": []}]
    tested = helper_instance()
    result = tested._get("/api/v4/systems", {"size": 100})
    assert result == {"systems": []}
    assert stale.mock_calls == [call()]
    assert refresh.mock_calls == [call()]
    assert url.mock_calls == [exp_url]
    assert fetch.mock_calls == [call("theUrl")]
    assert json_or_fail.mock_calls == [call("theBody")]
    reset_mocks()

    # the token died early: one retry, and only one
    stale.side_effect = [False]
    refresh.side_effect = [helper_tokens()]
    url.side_effect = ["theUrl", "theUrl"]
    fetch.side_effect = [AppException(401, "stale"), "theBody"]
    json_or_fail.side_effect = [{"systems": []}]
    tested = helper_instance()
    result = tested._get("/api/v4/systems", {"size": 100})
    assert result == {"systems": []}
    assert stale.mock_calls == [call()]
    assert refresh.mock_calls == [call()]
    assert url.mock_calls == [exp_url, exp_url]
    assert fetch.mock_calls == [call("theUrl"), call("theUrl")]
    assert json_or_fail.mock_calls == [call("theBody")]
    reset_mocks()

    # anything but a 401 is the caller's problem: refreshing would not help
    stale.side_effect = [False]
    url.side_effect = ["theUrl"]
    fetch.side_effect = [AppException(502, "Enphase could not be reached.")]
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested._get("/api/v4/systems", {"size": 100})
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "Enphase could not be reached."
    assert stale.mock_calls == [call()]
    assert refresh.mock_calls == []
    assert url.mock_calls == [exp_url]
    assert fetch.mock_calls == [call("theUrl")]
    assert json_or_fail.mock_calls == []
    reset_mocks()


@patch("usage.libraries.enphase_client.datetime", wraps=datetime)
def test__stale(mock_datetime: MagicMock) -> None:
    def reset_mocks() -> None:
        mock_datetime.reset_mock()

    tests: list[tuple[EnphaseTokens, bool, list[Any]]] = [
        # never authorised at all
        (EnphaseTokens(access_token="", refresh_token="theRefreshToken"), True, []),
        # no stated life: taken at its word until a call says otherwise
        (helper_tokens(), False, []),
        # comfortably in date
        (helper_tokens(NOW + timedelta(hours=2)), False, [call.now(UTC)]),
        # inside the skew, so refreshed a little early rather than on the boundary
        (helper_tokens(NOW + timedelta(seconds=120)), True, [call.now(UTC)]),
        (helper_tokens(NOW - timedelta(seconds=1)), True, [call.now(UTC)]),
    ]
    for tokens, expected, exp_calls in tests:
        mock_datetime.now.side_effect = [NOW]
        tested = helper_instance(tokens)
        result = tested._stale()
        assert result is expected
        assert mock_datetime.mock_calls == exp_calls
        reset_mocks()


def test__url() -> None:
    tested = helper_instance()
    result = tested._url("/api/v4/systems/3456789/telemetry/battery", {"start_at": 1789516800, "granularity": "day"})
    expected = (
        "https://api.enphaseenergy.com/api/v4/systems/3456789/telemetry/battery"
        "?start_at=1789516800&granularity=day&key=theApiKey"
    )
    assert result == expected


@patch.object(EnphaseClient, "_await_slot")
@patch("usage.libraries.enphase_client.urllib.request.urlopen")
@patch("usage.libraries.enphase_client.urllib.request.Request")
def test__fetch(request_class: MagicMock, urlopen: MagicMock, await_slot: MagicMock) -> None:
    request = MagicMock()
    response = MagicMock()

    def reset_mocks() -> None:
        request_class.reset_mock()
        urlopen.reset_mock()
        await_slot.reset_mock()
        request.reset_mock()
        response.reset_mock()

    exp_request = call(
        "https://api.enphaseenergy.com/api/v4/systems?key=theApiKey",
        headers={"Authorization": "Bearer theAccessToken", "Accept": "application/json"},
    )

    request_class.side_effect = [request]
    urlopen.return_value.__enter__.side_effect = [response]
    response.read.side_effect = [b"theBody"]
    tested = helper_instance()
    result = tested._fetch("https://api.enphaseenergy.com/api/v4/systems?key=theApiKey")
    expected = "theBody"
    assert result == expected
    # the plan is billed per request, so the count moves whatever the answer is
    assert tested.calls == 1
    assert request_class.mock_calls == [exp_request]
    exp_calls = [call(request, timeout=60), call().__enter__(), call().__exit__(None, None, None)]
    assert urlopen.mock_calls == exp_calls
    assert request.mock_calls == []
    assert response.mock_calls == [call.read()]
    # no request leaves without a slot under the per-minute ceiling
    assert await_slot.mock_calls == [call()]
    reset_mocks()

    tests: list[tuple[Exception, int, str]] = [
        (urllib.error.HTTPError("https://api.enphaseenergy.com", 429, "Too Many", {}, None), 429, "Enphase is refusing more requests: the plan's rate limit is spent."),  # type: ignore[arg-type]
        (urllib.error.URLError("no route"), 502, "Enphase could not be reached."),
        (OSError("socket died"), 502, "Enphase could not be reached."),
    ]
    for error, status_code, message in tests:
        request_class.side_effect = [request]
        urlopen.side_effect = [error]
        tested = helper_instance()
        with pytest.raises(AppException) as exc_info:
            tested._fetch("https://api.enphaseenergy.com/api/v4/systems?key=theApiKey")
        assert exc_info.value.status_code == status_code
        assert exc_info.value.message == message
        assert tested.calls == 1
        assert request_class.mock_calls == [exp_request]
        assert urlopen.mock_calls == [call(request, timeout=60)]
        assert request.mock_calls == []
        assert response.mock_calls == []
        assert await_slot.mock_calls == [call()]
        reset_mocks()


@patch.object(EnphaseClient, "_await_slot")
@patch("usage.libraries.enphase_client.urllib.request.urlopen")
@patch("usage.libraries.enphase_client.urllib.request.Request")
def test__token_call(request_class: MagicMock, urlopen: MagicMock, await_slot: MagicMock) -> None:
    request = MagicMock()
    response = MagicMock()

    def reset_mocks() -> None:
        request_class.reset_mock()
        urlopen.reset_mock()
        await_slot.reset_mock()
        request.reset_mock()
        response.reset_mock()

    # the application authenticates itself in a Basic header; the grant is in the query
    exp_request = call(
        "https://api.enphaseenergy.com/oauth/token?grant_type=refresh_token&refresh_token=theRefreshToken",
        data=b"",
        headers={
            "Authorization": "Basic dGhlQ2xpZW50SWQ6dGhlQ2xpZW50U2VjcmV0",
            "Accept": "application/json",
        },
    )
    params = {"grant_type": "refresh_token", "refresh_token": "theRefreshToken"}

    request_class.side_effect = [request]
    urlopen.return_value.__enter__.side_effect = [response]
    response.read.side_effect = [b'{"access_token": "theNewAccess", "refresh_token": "theNewRefresh"}']
    tested = helper_instance()
    result = tested._token_call(params, "theRefusal")
    expected = {"access_token": "theNewAccess", "refresh_token": "theNewRefresh"}
    assert result == expected
    # the OAuth endpoint is not the metered API: it is not billed to the plan
    assert tested.calls == 0
    assert request_class.mock_calls == [exp_request]
    exp_calls = [call(request, timeout=60), call().__enter__(), call().__exit__(None, None, None)]
    assert urlopen.mock_calls == exp_calls
    assert request.mock_calls == []
    assert response.mock_calls == [call.read()]
    # a refresh lands in the middle of a burst, so it queues with the rest
    assert await_slot.mock_calls == [call()]
    reset_mocks()

    # a 200 carrying no token is a refusal dressed as an answer
    request_class.side_effect = [request]
    urlopen.return_value.__enter__.side_effect = [response]
    response.read.side_effect = [b'{"error": "invalid_grant"}']
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested._token_call(params, "theRefusal")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "theRefusal"
    assert request_class.mock_calls == [exp_request]
    assert urlopen.mock_calls == exp_calls
    assert request.mock_calls == []
    assert response.mock_calls == [call.read()]
    assert await_slot.mock_calls == [call()]
    reset_mocks()

    tests: list[tuple[Exception, int, str]] = [
        # the grant itself was refused, which is what the caller's message explains
        (urllib.error.HTTPError("https://api.enphaseenergy.com", 400, "Bad Request", {}, None), 401, "theRefusal"),  # type: ignore[arg-type]
        (urllib.error.HTTPError("https://api.enphaseenergy.com", 401, "Unauthorized", {}, None), 401, "theRefusal"),  # type: ignore[arg-type]
        # anything else is read as an ordinary transport failure
        (urllib.error.HTTPError("https://api.enphaseenergy.com", 500, "Server Error", {}, None), 502, "Enphase could not be reached."),  # type: ignore[arg-type]
        (urllib.error.URLError("no route"), 502, "Enphase could not be reached."),
        (OSError("socket died"), 502, "Enphase could not be reached."),
    ]
    for error, status_code, message in tests:
        request_class.side_effect = [request]
        urlopen.side_effect = [error]
        tested = helper_instance()
        with pytest.raises(AppException) as exc_info:
            tested._token_call(params, "theRefusal")
        assert exc_info.value.status_code == status_code
        assert exc_info.value.message == message
        assert request_class.mock_calls == [exp_request]
        assert urlopen.mock_calls == [call(request, timeout=60)]
        assert request.mock_calls == []
        assert response.mock_calls == []
        assert await_slot.mock_calls == [call()]
        reset_mocks()


@patch("usage.libraries.enphase_client.datetime", wraps=datetime)
def test__store(mock_datetime: MagicMock) -> None:
    def reset_mocks() -> None:
        mock_datetime.reset_mock()

    mock_datetime.now.side_effect = [NOW]
    tested = helper_instance()
    result = tested._store({"access_token": "theNewAccess", "refresh_token": "theNewRefresh", "expires_in": 86400})
    expected = EnphaseTokens(
        access_token="theNewAccess",
        refresh_token="theNewRefresh",
        expires_at=datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
    )
    assert result == expected
    assert tested.tokens == expected
    assert mock_datetime.mock_calls == [call.now(UTC)]
    reset_mocks()

    # no replacement half: keeping the old one beats storing nothing at all
    tested = helper_instance()
    result = tested._store({"access_token": "theNewAccess"})
    expected = EnphaseTokens(access_token="theNewAccess", refresh_token="theRefreshToken", expires_at=None)
    assert result == expected
    assert tested.tokens == expected
    assert mock_datetime.mock_calls == []
    reset_mocks()


@patch.object(EnphaseClient, "_json")
def test__json_or_fail(mock_json: MagicMock) -> None:
    def reset_mocks() -> None:
        mock_json.reset_mock()

    mock_json.side_effect = [{"systems": []}]
    tested = helper_instance()
    result = tested._json_or_fail("theBody")
    assert result == {"systems": []}
    assert mock_json.mock_calls == [call("theBody")]
    reset_mocks()

    # a 200 that is not the API: a captive portal, an error page, a redirect
    mock_json.side_effect = [{}]
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested._json_or_fail("<html>")
    assert exc_info.value.status_code == 422
    assert exc_info.value.message == "Enphase answered with something that is not JSON."
    assert mock_json.mock_calls == [call("<html>")]
    reset_mocks()


def test__json() -> None:
    tested = helper_instance()
    tests: list[tuple[str, dict[str, Any]]] = [
        ('{"systems": []}', {"systems": []}),
        ("notJson", {}),
        ("[1, 2]", {}),
        ('"aString"', {}),
        ("", {}),
    ]
    for raw, expected in tests:
        result = tested._json(raw)
        assert result == expected


def test__day() -> None:
    tested = helper_instance()
    tests: list[tuple[str, date | None]] = [
        ("2026-09-16", date(2026, 9, 16)),
        ("  2026-09-16  ", date(2026, 9, 16)),
        ("16/09/2026", None),
        ("", None),
    ]
    for raw, expected in tests:
        result = tested._day(raw)
        assert result == expected


def test__kwh() -> None:
    tested = helper_instance()
    tests: list[tuple[float | None, float | None]] = [
        (12000, 12.0),
        (412, 0.412),
        (1, 0.001),
        (0, 0.0),
        (None, None),
    ]
    for watt_hours, expected in tests:
        result = tested._kwh(watt_hours)
        assert result == expected


def test__number() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, float | None]] = [
        (412, 412.0),
        ("412", 412.0),
        ("41.2", 41.2),
        (41.2, 41.2),
        # a flag is not a reading, however well it casts
        (True, None),
        (False, None),
        (None, None),
        ("nope", None),
        ({}, None),
    ]
    for raw, expected in tests:
        result = tested._number(raw)
        assert result == expected


@patch.object(EnphaseClient, "_refusal")
def test__http_failure(refusal: MagicMock) -> None:
    def reset_mocks() -> None:
        refusal.reset_mock()

    # the two credentials fail alike and are fixed differently, so Enphase's own
    # words are passed through for them
    tests: list[tuple[int, int]] = [(401, 401), (403, 401), (422, 422)]
    for code, status_code in tests:
        error = urllib.error.HTTPError("https://api.enphaseenergy.com", code, "Refused", {}, None)  # type: ignore[arg-type]
        refusal.side_effect = ["theRefusal"]
        tested = helper_instance()
        result = tested._http_failure(error)
        assert result.status_code == status_code
        assert result.message == "theRefusal"
        assert refusal.mock_calls == [call(error)]
        reset_mocks()

    tests_plain: list[tuple[int, int, str]] = [
        (429, 429, "Enphase is refusing more requests: the plan's rate limit is spent."),
        (500, 502, "Enphase could not be reached."),
        (404, 502, "Enphase could not be reached."),
    ]
    for code, status_code, message in tests_plain:
        error = urllib.error.HTTPError("https://api.enphaseenergy.com", code, "Refused", {}, None)  # type: ignore[arg-type]
        tested = helper_instance()
        result = tested._http_failure(error)
        assert result.status_code == status_code
        assert result.message == message
        assert refusal.mock_calls == []
        reset_mocks()


def test__refusal() -> None:
    tested = helper_instance()
    # Enphase names the credential that is wrong, whichever key it says it under
    tests: list[tuple[bytes, str]] = [
        (b'{"message": "api key not found"}', "Enphase refused the request: api key not found"),
        (b'{"error_description": "token expired"}', "Enphase refused the request: token expired"),
        (b'{"error": "invalid_token"}', "Enphase refused the request: invalid_token"),
        (b'{"message": "   "}', "Enphase refused the request; check the API key and the authorisation."),
        (b"{}", "Enphase refused the request; check the API key and the authorisation."),
        (b"notJson", "Enphase refused the request; check the API key and the authorisation."),
    ]
    for body, expected in tests:
        error = urllib.error.HTTPError("https://api.enphaseenergy.com", 401, "Refused", {}, io.BytesIO(body))  # type: ignore[arg-type]
        result = tested._refusal(error)
        assert result == expected

    # a very long explanation is cut rather than carried whole into last_error
    error = urllib.error.HTTPError(
        "https://api.enphaseenergy.com",
        401,
        "Refused",
        {},  # type: ignore[arg-type]
        io.BytesIO(json.dumps({"message": "x" * 400}).encode()),
    )
    result = tested._refusal(error)
    expected = f"Enphase refused the request: {'x' * 300}"
    assert result == expected

    # the body itself fails to arrive: the generic remedy is all there is to say
    broken = MagicMock()
    broken.read.side_effect = [OSError("socket died")]
    error = urllib.error.HTTPError("https://api.enphaseenergy.com", 401, "Refused", {}, broken)  # type: ignore[arg-type]
    result = tested._refusal(error)
    expected = "Enphase refused the request; check the API key and the authorisation."
    assert result == expected
    assert broken.mock_calls == [call.read()]


def test__await_slot() -> None:
    limiter = MagicMock()

    def reset_mocks() -> None:
        limiter.reset_mock()

    # no limiter at all: nothing to wait for
    tested = helper_instance()
    result = tested._await_slot()
    assert result is None
    assert limiter.mock_calls == []
    reset_mocks()

    # a slot was free, or came free while waiting
    limiter.acquire.side_effect = [True]
    tested = helper_instance(None, limiter)
    result = tested._await_slot()
    assert result is None
    assert limiter.mock_calls == [call.acquire("theApiKey", 60.0)]
    reset_mocks()

    # the ceiling is spent and the wait ran out: said plainly rather than a 429
    # from Enphase, which would have cost a call to find out
    limiter.acquire.side_effect = [False]
    tested = helper_instance(None, limiter)
    with pytest.raises(AppException) as exc_info:
        tested._await_slot()
    assert exc_info.value.status_code == 429
    assert exc_info.value.message == "Enphase is being asked as fast as the plan allows; try again in a minute."
    assert limiter.mock_calls == [call.acquire("theApiKey", 60.0)]
    reset_mocks()
