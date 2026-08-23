from __future__ import annotations

from pydantic import BaseModel


class ExtractRequest(BaseModel):
    meter_id: int
    image_base64: str
    media_type: str
    # 0 = all registers; a register id when the display cycles one register at a time.
    register_id: int = 0
