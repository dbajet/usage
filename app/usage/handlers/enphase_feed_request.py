from __future__ import annotations

from pydantic import BaseModel


class EnphaseFeedRequest(BaseModel):
    house_id: int
    client_id: str
    client_secret: str
    api_key: str
    # The code Enphase prints after the application is approved; it lasts minutes.
    code: str = ""
    # Empty asks the account: a single-system account needs no id at all.
    system_id: str = ""
    # The plan's monthly allowance; empty takes the free tier's.
    calls_budget: int = 0
