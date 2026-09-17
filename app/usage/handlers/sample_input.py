from __future__ import annotations

from pydantic import BaseModel


class SampleInput(BaseModel):
    entity_id: str
    value: float
    name: str = ""
    unit: str = ""
    measured_at: str = ""
    battery: float | None = None
    # Home Assistant's `last_reported`: when the thermometer was last heard from
    # at all, as against `measured_at`, which is when its value last changed.
    reported_at: str = ""
