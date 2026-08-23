from __future__ import annotations

from pydantic import BaseModel


class UserHouseRequest(BaseModel):
    user_id: int
    house_id: int
    linked: bool
