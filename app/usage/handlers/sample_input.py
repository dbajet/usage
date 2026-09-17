from __future__ import annotations

from pydantic import BaseModel


class SampleInput(BaseModel):
    entity_id: str
    value: float
    name: str = ""
    unit: str = ""
    measured_at: str = ""
    battery: float | None = None
    # When the thermometer was last heard from, as against `measured_at`, which
    # is when its value last changed. Worked out by the Home Assistant template,
    # which has to arrive at it sideways - see deploy/home-assistant.yaml.
    reported_at: str = ""
