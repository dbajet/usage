from __future__ import annotations

from typing import Any, NamedTuple


class WaterWindow(NamedTuple):
    """What a rolling 24 hours of the meter came to, which both alerts read.

    Rolling, never a calendar day: a stretch from one afternoon to the next
    counts exactly as much as one from midnight to midnight. `smallest` is the
    quietest interval in it, which answers whether the water ever stopped, and
    `total` is everything drawn, which answers whether too much was.
    """

    feed_id: int
    readings: int
    hours: float
    smallest: float
    total: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "readings": self.readings,
            "hours": self.hours,
            "smallest": self.smallest,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaterWindow:
        return cls(
            feed_id=int(data.get("feed_id") or 0),
            readings=int(data.get("readings") or 0),
            hours=float(data.get("hours") or 0.0),
            smallest=float(data.get("smallest") or 0.0),
            total=float(data.get("total") or 0.0),
        )
