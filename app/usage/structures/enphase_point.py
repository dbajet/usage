from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class EnphasePoint(NamedTuple):
    """One interval of a system's telemetry, in kilowatt-hours and percent.

    The three streams are fetched one call each and arrive as separate lists,
    so a point carries only the field its own stream filled in and the store
    merges them on the instant. `span_minutes` says how long the interval is,
    which is what separates the fine telemetry from the daily totals of the
    lifetime endpoints - they live in the same table and no query ever mixes
    them, or an hour would be counted twice inside its own day.

    `battery_level` is a level, not a counter: it is averaged over a bucket
    where the other two are summed, and it is the one field the lifetime
    endpoints cannot supply at all.
    """

    measured_at: datetime
    span_minutes: int = 15
    production: float | None = None
    consumption: float | None = None
    battery_level: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured_at": self.measured_at.isoformat(),
            "span_minutes": self.span_minutes,
            "production": self.production,
            "consumption": self.consumption,
            "battery_level": self.battery_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnphasePoint:
        return cls(
            measured_at=datetime.fromisoformat(str(data.get("measured_at") or "1970-01-01T00:00:00+00:00")),
            span_minutes=int(data.get("span_minutes") or 0),
            production=None if data.get("production") is None else float(data["production"]),
            consumption=None if data.get("consumption") is None else float(data["consumption"]),
            battery_level=None if data.get("battery_level") is None else float(data["battery_level"]),
        )
