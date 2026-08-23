from __future__ import annotations

from typing import Any, NamedTuple


class AuthLinkIssue(NamedTuple):
    link: str
    emailed: bool

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "link": self.link,
            "emailed": self.emailed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthLinkIssue:
        return cls(
            link=str(data.get("link") or ""),
            emailed=bool(data.get("emailed")),
        )
