from __future__ import annotations

from pydantic import BaseModel


class SensorUpdateRequest(BaseModel):
    name: str = ""
    unit: str = ""
    color: str = ""
    active: bool = True
    # The alert range, in the thermometer's own unit; null means "no bound on that side".
    threshold_min: float | None = None
    threshold_max: float | None = None
