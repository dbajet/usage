from __future__ import annotations

from pydantic import BaseModel


class SampleInput(BaseModel):
    entity_id: str
    value: float
    name: str = ""
    unit: str = ""
    measured_at: str = ""
    battery: float | None = None
    # Home Assistant's `last_updated`: when it last heard this value confirmed,
    # as against `measured_at`, which is when the value last changed.
    reported_at: str = ""
