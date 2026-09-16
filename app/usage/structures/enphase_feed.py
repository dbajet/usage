from __future__ import annotations

from datetime import date, datetime
from typing import Any, NamedTuple


class EnphaseFeed(NamedTuple):
    """One Enphase system, and the developer application used to reach it.

    Everything here belongs to the owner's own Enphase account - the three
    application secrets and the OAuth pair alike - so it lives sealed in the
    database and never leaves the server.

    The history is walked in two passes because the two resolutions cost
    wildly different amounts. `backfill_from` tracks the daily pass, which is
    two calls for the whole life of the system; `fine_from` tracks the
    quarter-hourly pass, which is three calls per day walked and is therefore
    stopped after a fortnight. `calls_used`, `calls_budget` and `calls_month`
    are the monthly allowance of the account's plan: unlike the water portal,
    Enphase counts every request, so the feed paces itself to make its own
    budget last the month rather than running fast and going silent on the 8th.
    """

    feed_id: int
    house_id: int
    client_id: str
    client_secret: str
    api_key: str
    system_id: str
    access_token: str = ""
    refresh_token: str = ""
    token_expires_at: datetime | None = None
    active: bool = True
    backfill_from: date | None = None
    backfill_done: bool = False
    fine_from: date | None = None
    fine_done: bool = False
    calls_used: int = 0
    calls_budget: int = 0
    calls_month: date | None = None
    last_point_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "house_id": self.house_id,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "api_key": self.api_key,
            "system_id": self.system_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.token_expires_at.isoformat() if self.token_expires_at is not None else "",
            "active": self.active,
            "backfill_from": self.backfill_from.isoformat() if self.backfill_from is not None else "",
            "backfill_done": self.backfill_done,
            "fine_from": self.fine_from.isoformat() if self.fine_from is not None else "",
            "fine_done": self.fine_done,
            "calls_used": self.calls_used,
            "calls_budget": self.calls_budget,
            "calls_month": self.calls_month.isoformat() if self.calls_month is not None else "",
            "last_point_at": self.last_point_at.isoformat() if self.last_point_at is not None else "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnphaseFeed:
        token_expires_at = str(data.get("token_expires_at") or "")
        backfill_from = str(data.get("backfill_from") or "")
        fine_from = str(data.get("fine_from") or "")
        calls_month = str(data.get("calls_month") or "")
        last_point_at = str(data.get("last_point_at") or "")
        return cls(
            feed_id=int(data.get("feed_id") or 0),
            house_id=int(data.get("house_id") or 0),
            client_id=str(data.get("client_id") or ""),
            client_secret=str(data.get("client_secret") or ""),
            api_key=str(data.get("api_key") or ""),
            system_id=str(data.get("system_id") or ""),
            access_token=str(data.get("access_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            token_expires_at=datetime.fromisoformat(token_expires_at) if token_expires_at else None,
            active=bool(data.get("active")),
            backfill_from=date.fromisoformat(backfill_from) if backfill_from else None,
            backfill_done=bool(data.get("backfill_done")),
            fine_from=date.fromisoformat(fine_from) if fine_from else None,
            fine_done=bool(data.get("fine_done")),
            calls_used=int(data.get("calls_used") or 0),
            calls_budget=int(data.get("calls_budget") or 0),
            calls_month=date.fromisoformat(calls_month) if calls_month else None,
            last_point_at=datetime.fromisoformat(last_point_at) if last_point_at else None,
        )
