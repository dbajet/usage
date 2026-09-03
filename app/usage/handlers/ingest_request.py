from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.sample_input import SampleInput


class IngestRequest(BaseModel):
    samples: list[SampleInput]
