from __future__ import annotations

from pydantic import BaseModel


class ReminderRequest(BaseModel):
    enabled: bool
