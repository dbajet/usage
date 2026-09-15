from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class WaterPoint(NamedTuple):
    """One interval of the export CSV, in cubic metres.

    `reading` is the meter's cumulative register and may be missing when the
    CSV reports it in a unit we cannot convert; `volume` is what ran through
    the meter during the interval, which is what the graph draws.
    """

    measured_at: datetime
    volume: float
    reading: float | None = None
    method: str = ""

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "measured_at": self.measured_at.isoformat(),
            "volume": self.volume,
            "reading": self.reading,
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaterPoint:
        return cls(
            measured_at=datetime.fromisoformat(str(data.get("measured_at") or "1970-01-01T00:00:00+00:00")),
            volume=float(data.get("volume") or 0.0),
            reading=None if data.get("reading") is None else float(data["reading"]),
            method=str(data.get("method") or ""),
        )
