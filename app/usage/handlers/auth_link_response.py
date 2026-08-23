from __future__ import annotations

from pydantic import BaseModel


class AuthLinkResponse(BaseModel):
    message: str
    dev_link: str = ""
