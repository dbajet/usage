from __future__ import annotations

from pydantic import BaseModel


class WaterAlertRequest(BaseModel):
    house_id: int
    enabled: bool = False
