from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.switch_bot_feed_request import SwitchBotFeedRequest


def test_inheritance() -> None:
    tested = SwitchBotFeedRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = SwitchBotFeedRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "token", "secret", "hub_ids"]
    assert result == expected


def test___init__() -> None:
    tested = SwitchBotFeedRequest(house_id=3, token="theToken", secret="theSecret", hub_ids=["FA7310762361"])
    result = tested.model_dump()
    expected = {"house_id": 3, "token": "theToken", "secret": "theSecret", "hub_ids": ["FA7310762361"]}
    assert result == expected

    tested = SwitchBotFeedRequest(house_id=3, token="theToken", secret="theSecret")
    result = tested.model_dump()
    expected = {"house_id": 3, "token": "theToken", "secret": "theSecret", "hub_ids": []}
    assert result == expected
