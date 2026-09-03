from __future__ import annotations

from pydantic import BaseModel


class SensorOrderRequest(BaseModel):
    house_id: int
    sensor_ids: list[int]
