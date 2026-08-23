from __future__ import annotations

from pydantic import BaseModel


class UserRequest(BaseModel):
    email: str
    name: str = ""
    is_admin: bool = False
