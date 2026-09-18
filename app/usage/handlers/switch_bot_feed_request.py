from __future__ import annotations

from pydantic import BaseModel


class SwitchBotFeedRequest(BaseModel):
    house_id: int
    token: str
    secret: str
    # The hubs of the account that stand in this house. Hubs, never devices: a
    # thermometer paired later is relayed by the same hub and joins on its own.
    hub_ids: list[str] = []
