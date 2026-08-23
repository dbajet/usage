from __future__ import annotations

from typing import Any, NamedTuple


class PasskeyRegistration(NamedTuple):
    credential_id: str
    public_key: str
    sign_count: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "credential_id": self.credential_id,
            "public_key": self.public_key,
            "sign_count": self.sign_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PasskeyRegistration:
        return cls(
            credential_id=str(data.get("credential_id") or ""),
            public_key=str(data.get("public_key") or ""),
            sign_count=int(data.get("sign_count") or 0),
        )
