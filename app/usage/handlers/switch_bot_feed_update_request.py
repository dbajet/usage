from __future__ import annotations

from pydantic import BaseModel


class SwitchBotFeedUpdateRequest(BaseModel):
    # Both empty keep the credentials already stored: neither is ever sent back
    # to the browser, so an edit that only moves a hub cannot retype them.
    token: str = ""
    secret: str = ""
    hub_ids: list[str] = []
    active: bool = True
