from __future__ import annotations

from pydantic import BaseModel


class MeterAxisRequest(BaseModel):
    meter_id: int
    # "left" (or empty) and "right" - the merged graph's two Y axes.
    axis: str = ""
