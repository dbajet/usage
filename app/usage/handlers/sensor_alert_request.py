from __future__ import annotations

from pydantic import BaseModel


class SensorAlertRequest(BaseModel):
    house_id: int = 0
    enabled: bool = False
