from __future__ import annotations

from pydantic import BaseModel


class WaterFeedRequest(BaseModel):
    house_id: int
    username: str
    password: str
    # Empty asks the account: a single-meter account needs no uuid at all.
    meter_uuid: str = ""
    hostname: str = ""
    export_unit: str = ""
    # Cubic metres; empty means no alert on the volume at all.
    daily_max: float | None = None
