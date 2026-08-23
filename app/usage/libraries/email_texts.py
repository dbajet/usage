from __future__ import annotations

from usage.constants.constants import Constants


class EmailTexts:
    """Plain-text email bodies, built as one line per list element."""

    @classmethod
    def sign_in_link(cls, link: str) -> tuple[str, list[str]]:
        subject = f"Your {Constants.app_name} sign-in link"
        body_lines = [
            "Hello,",
            "",
            f"Use this link to sign in to {Constants.app_name}:",
            link,
            "",
            f"The link works once and expires in {Constants.login_link_minutes} minutes.",
            "If you did not request it, you can ignore this email.",
        ]
        return subject, body_lines

    @classmethod
    def footer(cls, contact: str) -> list[str]:
        return [
            "",
            "—",
            f"{Constants.app_name} · {contact}",
        ]
