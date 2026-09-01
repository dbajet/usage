from __future__ import annotations

from pydantic import BaseModel


class HouseRequest(BaseModel):
    name: str
    timezone: str = ""
