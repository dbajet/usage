from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.enphase_feed_request import EnphaseFeedRequest


def test_inheritance() -> None:
    tested = EnphaseFeedRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = EnphaseFeedRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "client_id", "client_secret", "api_key", "code", "system_id", "calls_budget"]
    assert result == expected


def test___init__() -> None:
    tested = EnphaseFeedRequest(
        house_id=3,
        client_id="theClientId",
        client_secret="theClientSecret",
        api_key="theApiKey",
        code="theCode",
        system_id="3456789",
        calls_budget=10000,
    )
    result = tested.model_dump()
    expected = {
        "house_id": 3,
        "client_id": "theClientId",
        "client_secret": "theClientSecret",
        "api_key": "theApiKey",
        "code": "theCode",
        "system_id": "3456789",
        "calls_budget": 10000,
    }
    assert result == expected

    tested = EnphaseFeedRequest(
        house_id=3,
        client_id="theClientId",
        client_secret="theClientSecret",
        api_key="theApiKey",
    )
    result = tested.model_dump()
    expected = {
        "house_id": 3,
        "client_id": "theClientId",
        "client_secret": "theClientSecret",
        "api_key": "theApiKey",
        "code": "",
        "system_id": "",
        "calls_budget": 0,
    }
    assert result == expected
