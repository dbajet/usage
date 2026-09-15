from __future__ import annotations

import json
import urllib.error
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.libraries.eye_on_water_client import EyeOnWaterClient
from usage.structures.app_exception import AppException
from usage.structures.water_meter import WaterMeter
from usage.structures.water_point import WaterPoint

CSV_HEADER = (
    '"Account_ID","Meter_ID","Meter_SN","Read_Time","Timezone","Read","Read_Unit",'
    '"Read_Method","Flow_Time","Flow_Unit","Flow","Register"'
)


def helper_instance(hostname: str = "eyeonwater.com", export_unit: str = "Gallons") -> EyeOnWaterClient:
    return EyeOnWaterClient(hostname, "theUsername", "thePassword", export_unit)


def test___init__() -> None:
    tested = helper_instance()
    assert tested._hostname == "eyeonwater.com"
    assert tested._username == "theUsername"
    assert tested._password == "thePassword"
    assert tested._export_unit == "Gallons"
    assert tested._opener_built is None
    assert tested._signed_in is False

    tested = EyeOnWaterClient("", "theUsername", "thePassword")
    assert tested._hostname == "eyeonwater.com"
    assert tested._export_unit == "Gallons"


@patch.object(EyeOnWaterClient, "_points")
@patch.object(EyeOnWaterClient, "_download")
@patch.object(EyeOnWaterClient, "_await_export")
@patch.object(EyeOnWaterClient, "_initiate")
@patch.object(EyeOnWaterClient, "_sign_in")
def test_export(
    sign_in: MagicMock,
    initiate: MagicMock,
    await_export: MagicMock,
    download: MagicMock,
    points: MagicMock,
) -> None:
    def reset_mocks() -> None:
        sign_in.reset_mock()
        initiate.reset_mock()
        await_export.reset_mock()
        download.reset_mock()
        points.reset_mock()

    expected_points = [WaterPoint(measured_at=datetime(2026, 9, 14, 7, 14, tzinfo=UTC), volume=0.0034)]
    sign_in.side_effect = [None]
    initiate.side_effect = ["task:theTaskId"]
    await_export.side_effect = ["https://eyeonwater.com/reports/export436783"]
    download.side_effect = ["theCsv"]
    points.side_effect = [expected_points]

    tested = helper_instance()
    result = tested.export("theMeterUuid", date(2026, 9, 14), date(2026, 9, 15))
    assert result == expected_points
    assert sign_in.mock_calls == [call()]
    assert initiate.mock_calls == [call("theMeterUuid", date(2026, 9, 14), date(2026, 9, 15))]
    assert await_export.mock_calls == [call("task:theTaskId")]
    assert download.mock_calls == [call("https://eyeonwater.com/reports/export436783")]
    assert points.mock_calls == [call("theCsv")]
    reset_mocks()


@patch.object(EyeOnWaterClient, "_post")
@patch.object(EyeOnWaterClient, "_sign_in")
def test_meters(sign_in: MagicMock, post: MagicMock) -> None:
    def reset_mocks() -> None:
        sign_in.reset_mock()
        post.reset_mock()

    exp_post = call(
        "https://eyeonwater.com/api/2/residential/new_search",
        {"query": {"match_all": {}}},
    )

    hit = {
        "_source": {
            "meter": {"meter_uuid": "1234567890123456789", "meter_id": "900112233", "timezone": "US/Pacific"},
        },
    }
    # a hit with no uuid is no use, and neither is one shaped like nothing we know
    payload = json.dumps({"elastic_results": {"hits": {"hits": [hit, {"_source": {"meter": {}}}, "notAHit"]}}})
    sign_in.side_effect = [None]
    post.side_effect = [payload]
    tested = helper_instance()
    result = tested.meters()
    expected = [WaterMeter(uuid="1234567890123456789", meter_id="900112233", timezone="US/Pacific")]
    assert result == expected
    assert sign_in.mock_calls == [call()]
    assert post.mock_calls == [exp_post]
    reset_mocks()

    # every shape the answer can take without carrying a meter
    tests = ["", "notJson", "{}", '{"elastic_results": {}}', '{"elastic_results": {"hits": {}}}',
             '{"elastic_results": "nope"}', '{"elastic_results": {"hits": {"hits": "nope"}}}']
    for payload in tests:
        sign_in.side_effect = [None]
        post.side_effect = [payload]
        tested = helper_instance()
        result = tested.meters()
        assert result == []
        assert sign_in.mock_calls == [call()]
        assert post.mock_calls == [exp_post]
        reset_mocks()


@patch("usage.libraries.eye_on_water_client.urllib.request.build_opener")
@patch("usage.libraries.eye_on_water_client.urllib.request.HTTPCookieProcessor")
@patch("usage.libraries.eye_on_water_client.CookieJar")
def test__opener(cookie_jar_class: MagicMock, processor_class: MagicMock, build_opener: MagicMock) -> None:
    jar = MagicMock()
    processor = MagicMock()
    director = MagicMock()

    def reset_mocks() -> None:
        cookie_jar_class.reset_mock()
        processor_class.reset_mock()
        build_opener.reset_mock()
        jar.reset_mock()
        processor.reset_mock()
        director.reset_mock()

    cookie_jar_class.side_effect = [jar]
    processor_class.side_effect = [processor]
    build_opener.side_effect = [director]

    tested = helper_instance()
    result = tested._opener()
    assert result is director
    # built once, then reused: the session cookie must survive between calls
    result = tested._opener()
    assert result is director
    assert cookie_jar_class.mock_calls == [call()]
    assert processor_class.mock_calls == [call(jar)]
    assert build_opener.mock_calls == [call(processor)]
    assert jar.mock_calls == []
    assert processor.mock_calls == []
    assert director.mock_calls == []
    reset_mocks()


@patch.object(EyeOnWaterClient, "_opener")
def test__sign_in(opener: MagicMock) -> None:
    director = MagicMock()
    response = MagicMock()

    def reset_mocks() -> None:
        opener.reset_mock()
        director.reset_mock()
        response.reset_mock()

    exp_open = call.open(
        "https://eyeonwater.com/account/signin",
        b"username=theUsername&password=thePassword",
        timeout=120,
    )

    # the happy path
    opener.side_effect = [director]
    director.open.return_value.__enter__.side_effect = [response]
    response.read.side_effect = [b""]
    tested = helper_instance()
    result = tested._sign_in()
    assert result is None
    assert tested._signed_in is True
    assert opener.mock_calls == [call()]
    assert director.mock_calls == [exp_open, call.open().__enter__(), call.open().__exit__(None, None, None)]
    assert response.mock_calls == [call.read()]
    reset_mocks()

    # already signed in: nothing goes out
    tested._sign_in()
    assert opener.mock_calls == []
    assert director.mock_calls == []
    assert response.mock_calls == []
    reset_mocks()

    # the credentials, the rate limit and the rest
    tests = [
        (urllib.error.HTTPError("https://eyeonwater.com", 400, "Bad Request", {}, None), 401, "EyeOnWater rejected the username or password."),  # type: ignore[arg-type]
        (urllib.error.HTTPError("https://eyeonwater.com", 403, "Forbidden", {}, None), 429, "EyeOnWater is refusing more requests for now."),  # type: ignore[arg-type]
        (urllib.error.HTTPError("https://eyeonwater.com", 500, "Boom", {}, None), 502, "EyeOnWater could not be reached."),  # type: ignore[arg-type]
        (urllib.error.URLError("no route"), 502, "EyeOnWater could not be reached."),
        (OSError("broken"), 502, "EyeOnWater could not be reached."),
    ]
    for error, status_code, message in tests:
        opener.side_effect = [director]
        director.open.side_effect = [error]
        tested = helper_instance()
        with pytest.raises(AppException) as exc_info:
            tested._sign_in()
        assert exc_info.value.status_code == status_code
        assert exc_info.value.message == message
        assert tested._signed_in is False
        assert opener.mock_calls == [call()]
        assert director.mock_calls == [exp_open]
        assert response.mock_calls == []
        reset_mocks()


@patch.object(EyeOnWaterClient, "_stamp")
@patch.object(EyeOnWaterClient, "_fetch")
def test__initiate(fetch: MagicMock, stamp: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch.reset_mock()
        stamp.reset_mock()

    exp_url = (
        "https://eyeonwater.com/reports/export_initiate?export_unit=Gallons&site=residential"
        "&export_resolution=quarter_hourly&start-date=09%2F14%2F2026&end-date=09%2F15%2F2026"
        "&meter_uuid=theMeterUuid&row-format=range&export_all=false&_=1789470746572"
    )

    stamp.side_effect = [1789470746572]
    fetch.side_effect = ['{"task_id": "task:dbe6fdee09774fa8a90069f8aa4aa044"}']
    tested = helper_instance()
    result = tested._initiate("theMeterUuid", date(2026, 9, 14), date(2026, 9, 15))
    expected = "task:dbe6fdee09774fa8a90069f8aa4aa044"
    assert result == expected
    assert fetch.mock_calls == [call(exp_url)]
    assert stamp.mock_calls == [call()]
    reset_mocks()

    # the sign-in answers the login page: no task comes back
    stamp.side_effect = [1789470746572]
    fetch.side_effect = ["<html>the login page</html>"]
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested._initiate("theMeterUuid", date(2026, 9, 14), date(2026, 9, 15))
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "EyeOnWater did not start the export; the username or password was probably refused."
    assert fetch.mock_calls == [call(exp_url)]
    assert stamp.mock_calls == [call()]
    reset_mocks()


@patch("usage.libraries.eye_on_water_client.time")
@patch.object(EyeOnWaterClient, "_result_url")
@patch.object(EyeOnWaterClient, "_stamp")
@patch.object(EyeOnWaterClient, "_fetch")
def test__await_export(fetch: MagicMock, stamp: MagicMock, result_url: MagicMock, time_module: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch.reset_mock()
        stamp.reset_mock()
        result_url.reset_mock()
        time_module.reset_mock()

    exp_url = "https://eyeonwater.com/reports/export_check_status/task:theTaskId?_=1789470746669"

    # pending, then done on the second poll
    stamp.side_effect = [1789470746669, 1789470746669]
    fetch.side_effect = ['{"state": "pending"}', '{"state": "done", "result": {"url": "/reports/export436783"}}']
    result_url.side_effect = ["https://eyeonwater.com/reports/export436783"]
    tested = helper_instance()
    result = tested._await_export("task:theTaskId")
    expected = "https://eyeonwater.com/reports/export436783"
    assert result == expected
    assert fetch.mock_calls == [call(exp_url), call(exp_url)]
    assert stamp.mock_calls == [call(), call()]
    assert result_url.mock_calls == [call({"state": "done", "result": {"url": "/reports/export436783"}})]
    assert time_module.mock_calls == [call.sleep(2.0)]
    reset_mocks()

    # the export failed on their side
    stamp.side_effect = [1789470746669]
    fetch.side_effect = ['{"state": "error", "message": "theExportBroke"}']
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested._await_export("task:theTaskId")
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "theExportBroke"
    assert fetch.mock_calls == [call(exp_url)]
    assert stamp.mock_calls == [call()]
    assert result_url.mock_calls == []
    assert time_module.mock_calls == []
    reset_mocks()

    # ... without saying why
    stamp.side_effect = [1789470746669]
    fetch.side_effect = ['{"state": "error"}']
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested._await_export("task:theTaskId")
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "EyeOnWater could not build the export."
    assert fetch.mock_calls == [call(exp_url)]
    assert stamp.mock_calls == [call()]
    assert result_url.mock_calls == []
    assert time_module.mock_calls == []
    reset_mocks()

    # never finishes
    stamp.side_effect = [1789470746669] * 30
    fetch.side_effect = ['{"state": "pending"}'] * 30
    tested = helper_instance()
    with pytest.raises(AppException) as exc_info:
        tested._await_export("task:theTaskId")
    assert exc_info.value.status_code == 504
    assert exc_info.value.message == "EyeOnWater did not finish the export in time."
    assert fetch.mock_calls == [call(exp_url)] * 30
    assert stamp.mock_calls == [call()] * 30
    assert result_url.mock_calls == []
    assert time_module.mock_calls == [call.sleep(2.0)] * 29
    reset_mocks()


def test__result_url() -> None:
    tested = helper_instance()
    # The key has moved before, so the link is searched for rather than named.
    tests: list[tuple[dict[str, Any], str]] = [
        ({"result": {"url": "/reports/export436783"}}, "https://eyeonwater.com/reports/export436783"),
        ({"result": '{"url": "https://s3.example/export436783?signature=theSignature"}'}, "https://s3.example/export436783?signature=theSignature"),
        ({"result": {"file": {"download_url": "/reports/export436783"}}}, "https://eyeonwater.com/reports/export436783"),
        ({"result": {"location": "https://s3.example/export436783"}}, "https://s3.example/export436783"),
        ({"result": ["/reports/export436783"]}, "https://eyeonwater.com/reports/export436783"),
        ({"result": "reports/export436783"}, "https://eyeonwater.com/reports/export436783"),
        ({"url": "/reports/export436783"}, "https://eyeonwater.com/reports/export436783"),
    ]
    for status, expected in tests:
        result = tested._result_url(status)
        assert result == expected

    # Nothing link-shaped: the message carries the keys that did come back, so the
    # next shape can be read off it. A date is not mistaken for a path.
    tests_failing: list[tuple[dict[str, Any], str]] = [
        ({}, "{}"),
        ({"result": {}}, "{result{}}"),
        ({"state": "done", "result": "notJson"}, "{result, state}"),
        ({"state": "done", "result": {"params": {"date": "09/15/2026"}}}, "{result{params{...}}, state}"),
    ]
    for status, shape in tests_failing:
        with pytest.raises(AppException) as exc_info:
            tested._result_url(status)
        assert exc_info.value.status_code == 502
        assert exc_info.value.message == f"EyeOnWater finished the export without saying where it is; it sent {shape}."

    # When it says why, that is the message worth showing.
    with pytest.raises(AppException) as exc_info:
        tested._result_url({"state": "done", "result": {"message": "No meter found.", "state": "FAILURE"}})
    assert exc_info.value.message == "EyeOnWater did not produce an export: No meter found."


def test__refusal() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[dict[str, Any], str]] = [
        (
            {"state": "done", "result": {"message": "No meter found.", "state": "FAILURE"}},
            "EyeOnWater did not produce an export: No meter found.",
        ),
        (
            {"state": "done", "result": '{"message": "No data available"}'},
            "EyeOnWater did not produce an export: No data available",
        ),
        ({"state": "done", "message": "  Something went wrong  "}, "EyeOnWater did not produce an export: Something went wrong"),
        # a message longer than the banner can carry is cut, not dropped
        ({"result": {"message": "x" * 400}}, f"EyeOnWater did not produce an export: {'x' * 300}"),
        # nothing said at all: the shape is all there is to report
        ({"state": "done", "result": {"state": "FAILURE"}}, "EyeOnWater finished the export without saying where it is; it sent {result{state}, state}."),
        ({"state": "done", "result": "notJson"}, "EyeOnWater finished the export without saying where it is; it sent {result, state}."),
    ]
    for status, expected in tests:
        result = tested._refusal(status)
        assert result == expected


def test__first_link() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[Any, str]] = [
        ("/reports/export436783", "/reports/export436783"),
        ("https://s3.example/x", "https://s3.example/x"),
        ("reports/export436783", "reports/export436783"),
        ("09/15/2026", ""),
        ("done", ""),
        ("", ""),
        ({"a": {"b": "/x"}}, "/x"),
        ({"a": "done", "b": "/x"}, "/x"),
        (["done", "/x"], "/x"),
        ('{"url": "/x"}', "/x"),
        (7, ""),
        (None, ""),
    ]
    for value, expected in tests:
        result = tested._first_link(value)
        assert result == expected


def test__shape() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[Any, str]] = [
        ({}, "{}"),
        ({"state": "done"}, "{state}"),
        ({"result": {"url": "/x"}, "state": "done"}, "{result{url}, state}"),
        ({"a": {"b": {"c": {"d": 1}}}}, "{a{b{...}}}"),
        ({"rows": [1, 2]}, "{rows[...]}"),
        ({"rows": []}, "{rows[]}"),
        ('{"url": "/x"}', "{url}"),
        ("done", ""),
        (7, ""),
    ]
    for value, expected in tests:
        result = tested._shape(value)
        assert result == expected


@patch.object(EyeOnWaterClient, "_fetch")
def test__download(fetch: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch.reset_mock()

    fetch.side_effect = ["theCsv"]
    tested = helper_instance()
    result = tested._download("https://s3.example/export436783")
    expected = "theCsv"
    assert result == expected
    assert fetch.mock_calls == [call("https://s3.example/export436783")]
    reset_mocks()


@patch("usage.libraries.eye_on_water_client.urllib.request.Request")
@patch.object(EyeOnWaterClient, "_opener")
def test__post(opener: MagicMock, request_class: MagicMock) -> None:
    director = MagicMock()
    response = MagicMock()
    request = MagicMock()

    def reset_mocks() -> None:
        opener.reset_mock()
        request_class.reset_mock()
        director.reset_mock()
        response.reset_mock()
        request.reset_mock()

    exp_request = call(
        "https://eyeonwater.com/api/2/residential/new_search",
        data=b'{"query": {"match_all": {}}}',
        headers={"Content-Type": "application/json"},
    )

    opener.side_effect = [director]
    request_class.side_effect = [request]
    director.open.return_value.__enter__.side_effect = [response]
    response.read.side_effect = [b"theBody"]
    tested = helper_instance()
    result = tested._post("https://eyeonwater.com/api/2/residential/new_search", {"query": {"match_all": {}}})
    expected = "theBody"
    assert result == expected
    assert opener.mock_calls == [call()]
    assert request_class.mock_calls == [exp_request]
    assert director.mock_calls == [
        call.open(request, None, timeout=120),
        call.open().__enter__(),
        call.open().__exit__(None, None, None),
    ]
    assert response.mock_calls == [call.read()]
    assert request.mock_calls == []
    reset_mocks()

    tests = [
        (urllib.error.HTTPError("https://eyeonwater.com", 400, "Bad", {}, None), 401, "EyeOnWater rejected the username or password."),  # type: ignore[arg-type]
        (urllib.error.URLError("no route"), 502, "EyeOnWater could not be reached."),
    ]
    for error, status_code, message in tests:
        opener.side_effect = [director]
        request_class.side_effect = [request]
        director.open.side_effect = [error]
        tested = helper_instance()
        with pytest.raises(AppException) as exc_info:
            tested._post("https://eyeonwater.com/api/2/residential/new_search", {"query": {"match_all": {}}})
        assert exc_info.value.status_code == status_code
        assert exc_info.value.message == message
        assert opener.mock_calls == [call()]
        assert request_class.mock_calls == [exp_request]
        assert director.mock_calls == [call.open(request, None, timeout=120)]
        assert response.mock_calls == []
        assert request.mock_calls == []
        reset_mocks()


@patch.object(EyeOnWaterClient, "_opener")
def test__fetch(opener: MagicMock) -> None:
    director = MagicMock()
    response = MagicMock()

    def reset_mocks() -> None:
        opener.reset_mock()
        director.reset_mock()
        response.reset_mock()

    exp_open = call.open("https://eyeonwater.com/thePath", None, timeout=120)

    opener.side_effect = [director]
    director.open.return_value.__enter__.side_effect = [response]
    response.read.side_effect = [b"theBody"]
    tested = helper_instance()
    result = tested._fetch("https://eyeonwater.com/thePath")
    expected = "theBody"
    assert result == expected
    assert opener.mock_calls == [call()]
    assert director.mock_calls == [exp_open, call.open().__enter__(), call.open().__exit__(None, None, None)]
    assert response.mock_calls == [call.read()]
    reset_mocks()

    tests = [
        (urllib.error.HTTPError("https://eyeonwater.com", 403, "Forbidden", {}, None), 429, "EyeOnWater is refusing more requests for now."),  # type: ignore[arg-type]
        (urllib.error.URLError("no route"), 502, "EyeOnWater could not be reached."),
    ]
    for error, status_code, message in tests:
        opener.side_effect = [director]
        director.open.side_effect = [error]
        tested = helper_instance()
        with pytest.raises(AppException) as exc_info:
            tested._fetch("https://eyeonwater.com/thePath")
        assert exc_info.value.status_code == status_code
        assert exc_info.value.message == message
        assert opener.mock_calls == [call()]
        assert director.mock_calls == [exp_open]
        assert response.mock_calls == []
        reset_mocks()


def test__points() -> None:
    tested = helper_instance()

    # nothing at all: the meter published nothing for the range
    result = tested._points("")
    assert result == []

    rows = [
        CSV_HEADER,
        '"000-00000-000","900112233","900112233","2026-09-14 00:14","US/Pacific","182.0913","CCF","Network","2026-09-14 00:14:59","Gallons","0","single"',
        '"000-00000-000","900112233","900112233","2026-09-14 00:29","US/Pacific","182.3248","CCF","Estimated","2026-09-14 00:29:59","Gallons","2.54337662","single"',
        # no time, unreadable time, and a flow in a unit nobody knows: all skipped
        '"000-00000-000","900112233","900112233","","US/Pacific","182.3248","CCF","Network","","Gallons","0","single"',
        '"000-00000-000","900112233","900112233","not a date","US/Pacific","182.3248","CCF","Network","","Gallons","0","single"',
        '"000-00000-000","900112233","900112233","2026-09-14 00:44","US/Pacific","182.3248","CCF","Network","","Firkins","3","single"',
        # a reading in an unknown unit still yields its volume
        '"000-00000-000","900112233","900112233","2026-09-14 00:59","US/Pacific","182.3248","Firkins","Network","","Gallons","0","single"',
    ]
    result = tested._points("\n".join(rows))
    expected = [
        WaterPoint(measured_at=datetime(2026, 9, 14, 7, 14, tzinfo=UTC), volume=0.0, reading=515.625141, method="Network"),
        WaterPoint(measured_at=datetime(2026, 9, 14, 7, 29, tzinfo=UTC), volume=0.009628, reading=516.286339, method="Estimated"),
        WaterPoint(measured_at=datetime(2026, 9, 14, 7, 59, tzinfo=UTC), volume=0.0, reading=None, method="Network"),
    ]
    assert result == expected

    # rows that all fail to parse mean the export changed shape
    broken = [CSV_HEADER, '"000-00000-000","900112233","900112233","nope","US/Pacific","1","CCF","Network","","Gallons","0","single"']
    with pytest.raises(AppException) as exc_info:
        tested._points("\n".join(broken))
    assert exc_info.value.status_code == 422
    assert exc_info.value.message == "The EyeOnWater export was not in the expected format."

    # a range with nothing in it comes back as the header and one hollow row: that
    # is an empty month, not a changed format, and must not raise
    hollow = [CSV_HEADER, '"000-00000-000","900112233","900112233","","US/Pacific","","","","","Gallons","","single"']
    result = tested._points("\n".join(hollow))
    assert result == []


def test__is_blank() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[dict[str, str | None], bool]] = [
        ({"Read_Time": "", "Read": "", "Flow": ""}, True),
        ({"Read_Time": "  ", "Read": None, "Flow": ""}, True),
        ({}, True),
        ({"Read_Time": "2026-09-14 00:14", "Read": "", "Flow": ""}, False),
        ({"Read_Time": "", "Read": "182.0913", "Flow": ""}, False),
        ({"Read_Time": "", "Read": "", "Flow": "0"}, False),
    ]
    for row, expected in tests:
        result = tested._is_blank(row)
        assert result is expected


def test__moment() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[str, str, datetime | None, datetime | None]] = [
        ("", "US/Pacific", None, None),
        ("   ", "US/Pacific", None, None),
        ("not a date", "US/Pacific", None, None),
        ("2026-09-14 00:14", "US/Pacific", None, datetime(2026, 9, 14, 7, 14, tzinfo=UTC)),
        ("2026-09-14T00:14:30", "US/Pacific", None, datetime(2026, 9, 14, 7, 14, 30, tzinfo=UTC)),
        # no zone, and a zone nobody knows: read as UTC rather than dropped
        ("2026-09-14 00:14", "", None, datetime(2026, 9, 14, 0, 14, tzinfo=UTC)),
        ("2026-09-14 00:14", "Mars/Olympus", None, datetime(2026, 9, 14, 0, 14, tzinfo=UTC)),
        # the autumn fall-back: 01:14 comes round twice and the second one is later
        ("2026-11-01 01:14", "US/Pacific", None, datetime(2026, 11, 1, 8, 14, tzinfo=UTC)),
        (
            "2026-11-01 01:14",
            "US/Pacific",
            datetime(2026, 11, 1, 8, 14, tzinfo=UTC),
            datetime(2026, 11, 1, 9, 14, tzinfo=UTC),
        ),
        # a plain duplicate outside any fall-back keeps its instant
        (
            "2026-09-14 00:14",
            "US/Pacific",
            datetime(2026, 9, 14, 7, 14, tzinfo=UTC),
            datetime(2026, 9, 14, 7, 14, tzinfo=UTC),
        ),
    ]
    for raw, zone_name, previous, expected in tests:
        result = tested._moment(raw, zone_name, previous)
        assert result == expected


def test__cubic_meters() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[float | None, str, float | None]] = [
        (None, "CCF", None),
        (1.0, "CCF", 2.831685),
        (1.0, "ccf", 2.831685),
        (1.0, " Cubic Meters ", 1.0),
        (1000.0, "Liters", 1.0),
        (1.0, "GAL", 0.003785),
        (1.0, "Firkins", None),
        (1.0, "", None),
    ]
    for value, unit, expected in tests:
        result = tested._cubic_meters(value, unit)
        assert result == expected


def test__number() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[Any, float | None]] = [
        (None, None),
        ("", None),
        ("   ", None),
        ("nope", None),
        ("0", 0.0),
        ("182.0913", 182.0913),
        (3, 3.0),
    ]
    for raw, expected in tests:
        result = tested._number(raw)
        assert result == expected


def test__json() -> None:
    tested = EyeOnWaterClient
    tests: list[tuple[str, dict[str, Any]]] = [
        ('{"task_id": "task:x"}', {"task_id": "task:x"}),
        ("", {}),
        ("<html>", {}),
        ("[1, 2]", {}),
        ("null", {}),
    ]
    for raw, expected in tests:
        result = tested._json(raw)
        assert result == expected


@patch("usage.libraries.eye_on_water_client.time")
def test__stamp(time_module: MagicMock) -> None:
    def reset_mocks() -> None:
        time_module.reset_mock()

    tested = EyeOnWaterClient
    time_module.time.side_effect = [1789470746.572]
    result = tested._stamp()
    expected = 1789470746572
    assert result == expected
    assert time_module.mock_calls == [call.time()]
    reset_mocks()


def test__http_failure() -> None:
    tested = EyeOnWaterClient
    tests = [
        (400, 401, "EyeOnWater rejected the username or password."),
        (403, 429, "EyeOnWater is refusing more requests for now."),
        (500, 502, "EyeOnWater could not be reached."),
    ]
    for code, status_code, message in tests:
        error = urllib.error.HTTPError("https://eyeonwater.com", code, "Boom", {}, None)  # type: ignore[arg-type]
        result = tested._http_failure(error)
        assert isinstance(result, AppException)
        assert result.status_code == status_code
        assert result.message == message


def test__absolute() -> None:
    tested = helper_instance()
    tests = [
        ("/reports/export436783", "https://eyeonwater.com/reports/export436783"),
        ("reports/export436783", "https://eyeonwater.com/reports/export436783"),
        ("https://s3.example/export436783", "https://s3.example/export436783"),
        ("http://s3.example/export436783", "http://s3.example/export436783"),
    ]
    for url, expected in tests:
        result = tested._absolute(url)
        assert result == expected
