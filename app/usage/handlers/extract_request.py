from __future__ import annotations

from pydantic import BaseModel


class ExtractRequest(BaseModel):
    meter_id: int
    image_base64: str
    media_type: str
