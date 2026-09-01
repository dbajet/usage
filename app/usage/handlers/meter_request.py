from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.register_input import RegisterInput


class MeterRequest(BaseModel):
    house_id: int
    kind: str
    label: str = ""
    unit: str = ""
    monthly: bool = False
    registers: list[RegisterInput] = []
