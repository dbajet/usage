from __future__ import annotations

from pydantic import BaseModel


class RegisterInput(BaseModel):
    label: str = ""
    initial_value: float = 0.0
