from __future__ import annotations

from pydantic import BaseModel


class SensorUpdateRequest(BaseModel):
    name: str = ""
    unit: str = ""
    color: str = ""
    active: bool = True
