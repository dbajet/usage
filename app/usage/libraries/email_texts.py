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
    def reminder(cls, month_label: str, house: str, link: str) -> tuple[str, list[str]]:
        subject = f"{Constants.app_name}: time to record the readings of {house} for {month_label}"
        body_lines = [
            "Hello,",
            "",
            f"A new month has started - a good moment to record the meter readings of {house} for {month_label}:",
            link,
            "",
            "You receive this monthly reminder for this house;",
            "you can turn it off in Settings > Account at any time.",
        ]
        return subject, body_lines

    @classmethod
    def footer(cls, contact: str) -> list[str]:
        return [
            "",
            "—",
            f"{Constants.app_name} · {contact}",
        ]
