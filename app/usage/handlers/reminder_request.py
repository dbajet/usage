from __future__ import annotations

from pydantic import BaseModel


class ReminderRequest(BaseModel):
    house_id: int
    enabled: bool
