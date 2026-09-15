from __future__ import annotations

from datetime import date, datetime
from typing import Any, NamedTuple


class WaterFeed(NamedTuple):
    """An EyeOnWater account and meter to pull a house's water consumption from.

    The credentials are the utility account's own, so they live sealed in the
    database and never leave the server; `backfill_from` is how far back the
    first import has walked, and `empty_chunks` how many barren months it has
    met in a row - two of those and the history is taken to be exhausted.
    """

    feed_id: int
    house_id: int
    hostname: str
    username: str
    password: str
    meter_uuid: str
    export_unit: str
    active: bool = True
    backfill_from: date | None = None
    backfill_done: bool = False
    empty_chunks: int = 0
    last_point_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "house_id": self.house_id,
            "hostname": self.hostname,
            "username": self.username,
            "password": self.password,
            "meter_uuid": self.meter_uuid,
            "export_unit": self.export_unit,
            "active": self.active,
            "backfill_from": self.backfill_from.isoformat() if self.backfill_from is not None else "",
            "backfill_done": self.backfill_done,
            "empty_chunks": self.empty_chunks,
            "last_point_at": self.last_point_at.isoformat() if self.last_point_at is not None else "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaterFeed:
        backfill_from = str(data.get("backfill_from") or "")
        last_point_at = str(data.get("last_point_at") or "")
        return cls(
            feed_id=int(data.get("feed_id") or 0),
            house_id=int(data.get("house_id") or 0),
            hostname=str(data.get("hostname") or ""),
            username=str(data.get("username") or ""),
            password=str(data.get("password") or ""),
            meter_uuid=str(data.get("meter_uuid") or ""),
            export_unit=str(data.get("export_unit") or ""),
            active=bool(data.get("active")),
            backfill_from=date.fromisoformat(backfill_from) if backfill_from else None,
            backfill_done=bool(data.get("backfill_done")),
            empty_chunks=int(data.get("empty_chunks") or 0),
            last_point_at=datetime.fromisoformat(last_point_at) if last_point_at else None,
        )
