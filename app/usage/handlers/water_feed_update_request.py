from __future__ import annotations

from pydantic import BaseModel


class WaterFeedUpdateRequest(BaseModel):
    username: str
    # Empty asks the account, as on the way in.
    meter_uuid: str = ""
    # Empty keeps the password already stored: it is never sent back to the browser.
    password: str = ""
    hostname: str = ""
    export_unit: str = ""
    # Cubic metres; empty means no alert on the volume at all.
    daily_max: float | None = None
    active: bool = True
