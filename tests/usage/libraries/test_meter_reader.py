from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, call, patch

import pytest

from usage.libraries.meter_reader import MeterReader
from usage.structures.app_exception import AppException
from usage.structures.settings import Settings


def helper_settings(anthropic_api_key: str = "the-anthropic-key") -> Settings:
    return Settings(
        database_url="postgresql://tests",
        encryption_key="the-key",
        dev_auth_links=True,
        cookie_secure=False,
        base_url="https://usage.example",
        smtp_host="smtp.example",
        smtp_port=587,
        smtp_username="the-username",
        smtp_password="the-password",
        smtp_sender="sender@example.com",
        anthropic_api_key=anthropic_api_key,
        anthropic_model="claude-opus-5",
    )


def helper_instance(anthropic_api_key: str = "the-anthropic-key") -> MeterReader:
    return MeterReader(helper_settings(anthropic_api_key))


def test___init__() -> None:
    settings = helper_settings()
    tested = MeterReader(settings)
    assert tested._settings is settings


def test_is_configured() -> None:
    tests = [("the-anthropic-key", True), ("", False)]
    for anthropic_api_key, expected in tests:
        tested = helper_instance(anthropic_api_key)
        result = tested.is_configured()
        assert result is expected


@patch("usage.libraries.meter_reader.urllib.request.urlopen")
@patch("usage.libraries.meter_reader.urllib.request.Request")
@patch.object(MeterReader, "_values")
@patch.object(MeterReader, "_instructions")
def test_read(
    instructions: MagicMock,
    values: MagicMock,
    request_class: MagicMock,
    urlopen: MagicMock,
) -> None:
    request = MagicMock()
    response = MagicMock()

    def reset_mocks() -> None:
        instructions.reset_mock()
        values.reset_mock()
        request_class.reset_mock()
        urlopen.reset_mock()
        request.reset_mock()
        response.reset_mock()

    # not configured
    tested = helper_instance(anthropic_api_key="")
    with pytest.raises(AppException) as exc_info:
        tested.read("theBase64", "image/jpeg", ["HC", "HP"])
    assert exc_info.value.status_code == 503
    assert exc_info.value.message == "Photo extraction is not configured. Enter the value manually."
    assert instructions.mock_calls == []
    assert values.mock_calls == []
    assert request_class.mock_calls == []
    assert urlopen.mock_calls == []
    reset_mocks()

    tested = helper_instance()
    exp_payload = json.dumps(
        {
            "model": "claude-opus-5",
            "max_tokens": 4096,
            "fallbacks": "default",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": "theBase64",
                            },
                        },
                        {"type": "text", "text": "line one\nline two"},
                    ],
                },
            ],
        }
    ).encode("utf-8")
    exp_request_call = call(
        "https://api.anthropic.com/v1/messages",
        data=exp_payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": "the-anthropic-key",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "server-side-fallback-2026-07-01",
        },
    )

    # happy path
    instructions.side_effect = [["line one", "line two"]]
    values.side_effect = [[17273.0, 158.0]]
    request_class.side_effect = [request]
    body = {"content": [{"type": "text", "text": '{"values": [17273, 158]}'}]}
    response.__enter__.return_value.read.side_effect = [json.dumps(body).encode("utf-8")]
    urlopen.side_effect = [response]
    result = tested.read("theBase64", "image/jpeg", ["HC", "HP"])
    expected = [17273.0, 158.0]
    assert result == expected
    assert instructions.mock_calls == [call(["HC", "HP"])]
    assert values.mock_calls == [call(body, 2)]
    assert request_class.mock_calls == [exp_request_call]
    assert urlopen.mock_calls == [call(request, timeout=120)]
    assert response.__enter__.return_value.read.mock_calls == [call()]
    reset_mocks()

    # the service is unreachable
    instructions.side_effect = [["line one", "line two"]]
    request_class.side_effect = [request]
    urlopen.side_effect = [urllib.error.URLError("down")]
    with pytest.raises(AppException) as exc_info:
        tested.read("theBase64", "image/jpeg", ["HC", "HP"])
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "The photo could not be analyzed. Try again or enter the value manually."
    assert instructions.mock_calls == [call(["HC", "HP"])]
    assert values.mock_calls == []
    assert request_class.mock_calls == [exp_request_call]
    assert urlopen.mock_calls == [call(request, timeout=120)]
    reset_mocks()

    # the response is not valid json
    instructions.side_effect = [["line one", "line two"]]
    request_class.side_effect = [request]
    response.__enter__.return_value.read.side_effect = [b"notJson"]
    urlopen.side_effect = [response]
    with pytest.raises(AppException) as exc_info:
        tested.read("theBase64", "image/jpeg", ["HC", "HP"])
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "The photo could not be analyzed. Try again or enter the value manually."
    assert instructions.mock_calls == [call(["HC", "HP"])]
    assert values.mock_calls == []
    assert request_class.mock_calls == [exp_request_call]
    assert urlopen.mock_calls == [call(request, timeout=120)]
    reset_mocks()


def test__instructions() -> None:
    tested = MeterReader
    tests = [
        (
            ["HC", "HP"],
            [
                "You are reading a photo of a utility meter (or a car odometer).",
                "The meter has 2 register(s), in this order: HC, HP.",
                "Read the current counter value of each register from the photo.",
                "Digital or odometer displays: read the digits left to right and include the fractional part.",
                "Water meter LCDs almost always have a decimal point (often faint) before the last three",
                "digits - look closely for it; e.g. an LCD showing 004359754 is 004359.754 and reads 4359.754.",
                "Clock-style dials: order the dials by their multiplier labels (largest first), read one digit",
                "per dial and concatenate them into a single number - do not multiply by the labels.",
                "Adjacent dials rotate in opposite directions - always follow each dial's printed digit order.",
                "A dial's digit is the one its pointer has last PASSED, never the one it is approaching:",
                "of the two digits around the pointer, choose the one that comes earlier in that dial's",
                "printed rotation order (between 9 and 0 that is 9). When a pointer looks exactly on a digit,",
                "confirm with the dial to its right: if that dial has not completed its lap back to 0, the",
                "pointer has not reached the digit yet - use the previous one. Ignore the small test dials.",
                "Ignore serial numbers, dates and units.",
                "Photos can be double-exposed: every stroke then shows a ghost copy at a fixed offset -",
                "check the unit label and the other digits for the same doubling. Read only the primary",
                "copy of each digit, and count a digit as 8 only when its two loops are exactly vertically",
                "aligned: two loops offset along the ghosting direction are a 0 and its ghost.",
                "Before answering, verify the reading digit by digit: for each digit (or dial) write one",
                "short line naming the lit segments of its primary copy (A top, B upper-right, C lower-right,",
                "D bottom, E lower-left, F upper-left, G middle) - or the pointer position - and the digit",
                "you conclude.",
                'Then finish with this JSON alone on the last line: {"values": [...]}',
                "with one number per register in the order above, or null when a register cannot be read.",
            ],
        ),
        (
            [""],
            [
                "You are reading a photo of a utility meter (or a car odometer).",
                "The meter has 1 register(s), in this order: register 1.",
                "Read the current counter value of each register from the photo.",
                "Digital or odometer displays: read the digits left to right and include the fractional part.",
                "Water meter LCDs almost always have a decimal point (often faint) before the last three",
                "digits - look closely for it; e.g. an LCD showing 004359754 is 004359.754 and reads 4359.754.",
                "Clock-style dials: order the dials by their multiplier labels (largest first), read one digit",
                "per dial and concatenate them into a single number - do not multiply by the labels.",
                "Adjacent dials rotate in opposite directions - always follow each dial's printed digit order.",
                "A dial's digit is the one its pointer has last PASSED, never the one it is approaching:",
                "of the two digits around the pointer, choose the one that comes earlier in that dial's",
                "printed rotation order (between 9 and 0 that is 9). When a pointer looks exactly on a digit,",
                "confirm with the dial to its right: if that dial has not completed its lap back to 0, the",
                "pointer has not reached the digit yet - use the previous one. Ignore the small test dials.",
                "Ignore serial numbers, dates and units.",
                "Photos can be double-exposed: every stroke then shows a ghost copy at a fixed offset -",
                "check the unit label and the other digits for the same doubling. Read only the primary",
                "copy of each digit, and count a digit as 8 only when its two loops are exactly vertically",
                "aligned: two loops offset along the ghosting direction are a 0 and its ghost.",
                "Before answering, verify the reading digit by digit: for each digit (or dial) write one",
                "short line naming the lit segments of its primary copy (A top, B upper-right, C lower-right,",
                "D bottom, E lower-left, F upper-left, G middle) - or the pointer position - and the digit",
                "you conclude.",
                'Then finish with this JSON alone on the last line: {"values": [...]}',
                "with one number per register in the order above, or null when a register cannot be read.",
            ],
        ),
    ]
    for register_labels, expected in tests:
        result = tested._instructions(register_labels)
        assert result == expected, f"---> {register_labels}"


def test__values() -> None:
    tested = MeterReader

    # happy paths
    tests = [
        ({"content": [{"type": "text", "text": '{"values": [17273, 158.5]}'}]}, 2, [17273.0, 158.5]),
        ({"content": [{"type": "text", "text": '```json\n{"values": [10]}\n```'}]}, 1, [10.0]),
        ({"content": [{"type": "text", "text": 'digit 1: A B G C D -> 3\ndigit 2: A F G C D -> 5\n{"values": [35603]}'}]}, 1, [35603.0]),
        ({"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": '{"values": [null, 4]}'}]}, 2, [None, 4.0]),
        ({"content": [{"type": "text", "text": '{"values": [true]}'}]}, 1, [None]),
    ]
    for data, count, expected in tests:
        result = tested._values(data, count)
        assert result == expected, f"---> {data}"

    # error cases
    error_tests = [
        {"stop_reason": "refusal", "content": []},
        {"content": [{"type": "text", "text": "not json"}]},
        {"content": [{"type": "text", "text": '{"values": [1, 2]}'}]},
        {"content": [{"type": "text", "text": '{"values": "no"}'}]},
        {"content": [{"type": "text", "text": '{"other": 1}'}]},
        {"content": []},
        {},
    ]
    for error_data in error_tests:
        with pytest.raises(AppException) as exc_info:
            tested._values(error_data, 1)
        assert exc_info.value.status_code == 502, f"---> {error_data}"
        assert exc_info.value.message == "The photo could not be analyzed. Try again or enter the value manually.", f"---> {error_data}"
