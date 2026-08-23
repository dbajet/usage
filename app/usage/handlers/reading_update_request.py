from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.reading_value_input import ReadingValueInput


class ReadingUpdateRequest(BaseModel):
    read_on: str
    values: list[ReadingValueInput] = []
