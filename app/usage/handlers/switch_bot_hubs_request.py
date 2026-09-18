from __future__ import annotations

from pydantic import BaseModel


class SwitchBotHubsRequest(BaseModel):
    """Ask an account what it has, grouped by hub, before any of it is stored."""

    house_id: int
    token: str
    secret: str
