from __future__ import annotations

from typing import Any, NamedTuple


class EnphaseSystem(NamedTuple):
    """A system as the Enphase account lists it.

    The account is asked which systems it has rather than a person being asked
    to copy a number off the Enlighten URL, for the same reason the water meter
    is: an id that is wrong by one digit answers with an empty telemetry page
    rather than a refusal, which looks exactly like a system that produced
    nothing that day.
    """

    system_id: str
    name: str = ""
    status: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"system_id": self.system_id, "name": self.name, "status": self.status}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnphaseSystem:
        return cls(
            system_id=str(data.get("system_id") or ""),
            name=str(data.get("name") or ""),
            status=str(data.get("status") or ""),
        )
