from __future__ import annotations

from pydantic import BaseModel


class MeterUpdateRequest(BaseModel):
    label: str = ""
    unit: str = ""
    active: bool = True
