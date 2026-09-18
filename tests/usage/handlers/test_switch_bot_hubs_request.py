from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.switch_bot_hubs_request import SwitchBotHubsRequest


def test_inheritance() -> None:
    tested = SwitchBotHubsRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = SwitchBotHubsRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "token", "secret"]
    assert result == expected


def test___init__() -> None:
    tested = SwitchBotHubsRequest(house_id=3, token="theToken", secret="theSecret")
    result = tested.model_dump()
    expected = {"house_id": 3, "token": "theToken", "secret": "theSecret"}
    assert result == expected
