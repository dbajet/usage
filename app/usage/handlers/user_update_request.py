from __future__ import annotations

from pydantic import BaseModel


class UserUpdateRequest(BaseModel):
    name: str = ""
    is_admin: bool = False
