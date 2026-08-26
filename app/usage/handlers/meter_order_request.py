from __future__ import annotations

from pydantic import BaseModel


class MeterOrderRequest(BaseModel):
    house_id: int
    meter_ids: list[int]
