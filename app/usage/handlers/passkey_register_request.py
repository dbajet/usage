from __future__ import annotations

from pydantic import BaseModel


class PasskeyRegisterRequest(BaseModel):
    credential_id: str
    attestation_object: str
    client_data: str
