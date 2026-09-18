from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class SwitchBotFeed(NamedTuple):
    """A SwitchBot account, and the hubs of it that stand in this house.

    The token and the secret are the account's own, so they live sealed in the
    database and never leave the server. `hub_ids` is what makes one account
    serve two houses without either seeing the other's thermometers: a device
    is followed when the hub relaying it is one of these.

    Hubs rather than devices, because a device list is a snapshot and a hub is
    a standing answer - a thermometer paired next year is relayed by the same
    hub and appears on its own, where a ticked list of devices would silently
    miss it.
    """

    feed_id: int
    house_id: int
    token: str
    secret: str
    hub_ids: tuple[str, ...] = ()
    active: bool = True
    # The secret in the webhook URL, which has to be recoverable rather than
    # only hashed: it is what the app registers with SwitchBot.
    event_token: str = ""
    # When SwitchBot last accepted that registration. Unset means it has never
    # worked, and is what makes the sync try again.
    webhook_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "house_id": self.house_id,
            "token": self.token,
            "secret": self.secret,
            "hub_ids": list(self.hub_ids),
            "active": self.active,
            "event_token": self.event_token,
            "webhook_at": None if self.webhook_at is None else self.webhook_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwitchBotFeed:
        webhook_at = data.get("webhook_at")
        return cls(
            feed_id=int(data.get("feed_id") or 0),
            house_id=int(data.get("house_id") or 0),
            token=str(data.get("token") or ""),
            secret=str(data.get("secret") or ""),
            hub_ids=tuple(str(hub_id) for hub_id in data.get("hub_ids") or ()),
            active=bool(data.get("active")),
            event_token=str(data.get("event_token") or ""),
            webhook_at=None if webhook_at is None else datetime.fromisoformat(str(webhook_at)),
        )
