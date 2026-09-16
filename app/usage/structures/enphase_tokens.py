from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple


class EnphaseTokens(NamedTuple):
    """One OAuth2 pair for an Enphase application, and when the access half dies.

    Enphase rotates the refresh token on every use: the pair that comes back
    from a refresh replaces the one that was sent, and the old one stops
    working. Storing the new pair is therefore not housekeeping but the only
    thing keeping the feed alive - a refresh whose answer is thrown away locks
    the account out until somebody authorises it again by hand.
    """

    access_token: str
    refresh_token: str
    expires_at: datetime | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at is not None else "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnphaseTokens:
        expires_at = str(data.get("expires_at") or "")
        return cls(
            access_token=str(data.get("access_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        )
