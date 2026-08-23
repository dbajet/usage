from __future__ import annotations

from usage.libraries.email_texts import EmailTexts


def test_sign_in_link() -> None:
    tested = EmailTexts
    result = tested.sign_in_link("https://usage.example.com/?login=theToken")
    expected = (
        "Your Usage sign-in link",
        [
            "Hello,",
            "",
            "Use this link to sign in to Usage:",
            "https://usage.example.com/?login=theToken",
            "",
            "The link works once and expires in 15 minutes.",
            "If you did not request it, you can ignore this email.",
        ],
    )
    assert result == expected


def test_footer() -> None:
    tested = EmailTexts
    result = tested.footer("usage@edgy.world")
    expected = [
        "",
        "—",
        "Usage · usage@edgy.world",
    ]
    assert result == expected
