from __future__ import annotations

from pydantic import BaseModel


class ReadingValueInput(BaseModel):
    register_id: int
    value: float
