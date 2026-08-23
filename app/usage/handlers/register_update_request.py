from __future__ import annotations

from pydantic import BaseModel


class RegisterUpdateRequest(BaseModel):
    label: str = ""
    initial_value: float = 0.0
    active: bool = True
