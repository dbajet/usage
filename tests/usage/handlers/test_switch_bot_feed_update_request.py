from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.switch_bot_feed_update_request import SwitchBotFeedUpdateRequest


def test_inheritance() -> None:
    tested = SwitchBotFeedUpdateRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = SwitchBotFeedUpdateRequest
    result = list(tested.model_fields.keys())
    expected = ["token", "secret", "hub_ids", "active"]
    assert result == expected


def test___init__() -> None:
    tested = SwitchBotFeedUpdateRequest(token="theToken", secret="theSecret", hub_ids=["FA7310762361"], active=False)
    result = tested.model_dump()
    expected = {"token": "theToken", "secret": "theSecret", "hub_ids": ["FA7310762361"], "active": False}
    assert result == expected

    tested = SwitchBotFeedUpdateRequest()
    result = tested.model_dump()
    expected = {"token": "", "secret": "", "hub_ids": [], "active": True}
    assert result == expected
