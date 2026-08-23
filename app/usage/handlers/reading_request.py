from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.reading_value_input import ReadingValueInput


class ReadingRequest(BaseModel):
    meter_id: int
    read_on: str
    source: str = "manual"
    values: list[ReadingValueInput] = []
