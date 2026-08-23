from __future__ import annotations

from typing import Any, NamedTuple


class SessionUser(NamedTuple):
    user_id: int
    email: str
    name: str
    is_admin: bool

    def to_dict(self) -> dict[str, int | str | bool]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "is_admin": self.is_admin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionUser:
        return cls(
            user_id=int(data.get("user_id") or 0),
            email=str(data.get("email") or ""),
            name=str(data.get("name") or ""),
            is_admin=bool(data.get("is_admin")),
        )
