from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.enphase_feed_update_request import EnphaseFeedUpdateRequest


def test_inheritance() -> None:
    tested = EnphaseFeedUpdateRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = EnphaseFeedUpdateRequest
    result = list(tested.model_fields.keys())
    expected = ["client_id", "client_secret", "api_key", "code", "system_id", "calls_budget", "active"]
    assert result == expected


def test___init__() -> None:
    tested = EnphaseFeedUpdateRequest(
        client_id="theClientId",
        client_secret="theClientSecret",
        api_key="theApiKey",
        code="theCode",
        system_id="3456789",
        calls_budget=10000,
        active=False,
    )
    result = tested.model_dump()
    expected = {
        "client_id": "theClientId",
        "client_secret": "theClientSecret",
        "api_key": "theApiKey",
        "code": "theCode",
        "system_id": "3456789",
        "calls_budget": 10000,
        "active": False,
    }
    assert result == expected

    tested = EnphaseFeedUpdateRequest(client_id="theClientId")
    result = tested.model_dump()
    expected = {
        "client_id": "theClientId",
        "client_secret": "",
        "api_key": "",
        "code": "",
        "system_id": "",
        "calls_budget": 0,
        "active": True,
    }
    assert result == expected
