from __future__ import annotations

from typing import Any, NamedTuple


class WaterLeak(NamedTuple):
    """A day of water that never stopped running: what the alert email reports.

    `smallest` is the quietest interval of the day - the point of the whole test
    is that it is above zero, so it says how much was still flowing at the
    house's quietest moment.
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
    def from_dict(cls, data: dict[str, Any]) -> WaterLeak:
        return cls(
            feed_id=int(data.get("feed_id") or 0),
            readings=int(data.get("readings") or 0),
            hours=float(data.get("hours") or 0.0),
            smallest=float(data.get("smallest") or 0.0),
            total=float(data.get("total") or 0.0),
        )
