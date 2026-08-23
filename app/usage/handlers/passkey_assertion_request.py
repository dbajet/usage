from __future__ import annotations

from pydantic import BaseModel


class PasskeyAssertionRequest(BaseModel):
    credential_id: str
    authenticator_data: str
    client_data: str
    signature: str
