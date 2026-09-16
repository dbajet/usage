from __future__ import annotations

from pydantic import BaseModel


class EnphaseFeedUpdateRequest(BaseModel):
    client_id: str
    # Empty keeps what is already stored: neither is ever sent back to the browser.
    client_secret: str = ""
    api_key: str = ""
    # Empty keeps the stored authorisation; a fresh code replaces it.
    code: str = ""
    system_id: str = ""
    calls_budget: int = 0
    active: bool = True
