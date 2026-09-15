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
    active: bool = True
