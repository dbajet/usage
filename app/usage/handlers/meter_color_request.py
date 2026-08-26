from __future__ import annotations

from pydantic import BaseModel


class MeterColorRequest(BaseModel):
    meter_id: int
    # A #rrggbb value, or empty for the default palette colour.
    color: str = ""
