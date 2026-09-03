from __future__ import annotations

from pydantic import BaseModel


class SampleInput(BaseModel):
    entity_id: str
    value: float
    name: str = ""
    unit: str = ""
    measured_at: str = ""
