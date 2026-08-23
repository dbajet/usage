from __future__ import annotations

from pydantic import BaseModel


class AuthVerifyLinkRequest(BaseModel):
    token: str
