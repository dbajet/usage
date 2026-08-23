from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
from usage.libraries.email_texts import EmailTexts
from usage.structures.app_exception import AppException
from usage.structures.auth_link_issue import AuthLinkIssue
from usage.structures.session_user import SessionUser
from usage.structures.settings import Settings


class AuthCommand:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        email_sender: EmailSender,
    ) -> None:
        self._database = database
        self._settings = settings
        self._email_sender = email_sender

    def request_link(self, email: str, origin: str) -> AuthLinkIssue:
        """Issue a magic sign-in link, but only for an existing account.

        Sign-in never creates accounts (admins do), and never reveals whether
        an email has one: unknown emails get the same response, and the
        elapsed time is padded to a floor so both paths take about as long.
        """
        started = time.monotonic()
        normalized_email = self._normalize_email(email)
        if not self._is_valid_email(normalized_email):
            raise AppException(400, "Enter a valid email address.")
        email_hash = self._database.blind_index(normalized_email)
        link = ""
        user = self._database.fetch_one("SELECT id FROM users WHERE email_hash = %s", (email_hash,))
        if user is not None:
            if token := self._issue_link(email_hash):
                link = f"{self._settings.base_url or origin}/?login={token}"
        emailed = False
        if link:
            subject, body_lines = EmailTexts.sign_in_link(link)
            emailed = self._email_sender.send(normalized_email, subject, body_lines)
            if not emailed and not self._settings.dev_auth_links:
                raise AppException(502, "The sign-in email could not be sent. Try again later.")
        self._pad_to_minimum(started)
        result = AuthLinkIssue(link=link, emailed=emailed)
        return result

    def _issue_link(self, email_hash: str) -> str:
        result = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + timedelta(minutes=Constants.login_link_minutes)).isoformat()
        with self._database.transaction():
            self._database.execute("DELETE FROM login_links WHERE expires_at < %s", (datetime.now(UTC).isoformat(),))
            active = self._database.fetch_one(
                "SELECT COUNT(*) AS count FROM login_links WHERE email_hash = %s",
                (email_hash,),
            )
            if active is not None and int(active["count"]) >= Constants.login_links_active_max:
                # Over quota: the same generic outcome as an unknown email.
                return ""
            self._database.execute(
                "INSERT INTO login_links(email_hash, token_hash, expires_at) VALUES (%s, %s, %s)",
                (email_hash, self._hash(result), expires_at),
            )
        return result

    def _pad_to_minimum(self, started: float) -> None:
        remaining = Constants.login_link_min_seconds - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)

    def verify_link(self, token: str) -> str:
        stripped = token.strip()
        if not stripped:
            raise AppException(401, "The sign-in link is invalid or expired.")
        row = self._database.fetch_one(
            """
            SELECT id, email_hash FROM login_links
            WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s
            """,
            (self._hash(stripped), datetime.now(UTC).isoformat()),
        )
        if row is None:
            raise AppException(401, "The sign-in link is invalid or expired.")
        user = self._database.fetch_one("SELECT id FROM users WHERE email_hash = %s", (row["email_hash"],))
        if user is None:
            # Links are only issued to existing accounts; one that vanished
            # since gets the same generic failure.
            raise AppException(401, "The sign-in link is invalid or expired.")
        user_id = int(user["id"])
        result = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + timedelta(days=Constants.session_days)).isoformat()
        with self._database.transaction():
            self._database.execute("UPDATE login_links SET used_at = now() WHERE id = %s", (row["id"],))
            self._database.execute(
                "INSERT INTO sessions(user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (user_id, self._hash(result), expires_at),
            )
            self._database.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
        return result

    def user_from_token(self, token: str) -> SessionUser:
        row = self._database.fetch_one(
            """
            SELECT users.id AS user_id, users.email_sealed AS email,
                   users.name_sealed AS name, users.is_admin
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = %s AND sessions.expires_at > %s
            """,
            (self._hash(token), datetime.now(UTC).isoformat()),
        )
        if row is None:
            raise AppException(401, "Authentication required.")
        return SessionUser.from_dict(self._database.decrypt_row(row, ("email", "name")))

    def logout(self, token: str) -> None:
        self._database.execute("DELETE FROM sessions WHERE token_hash = %s", (self._hash(token),))

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _is_valid_email(self, email: str) -> bool:
        return "@" in email and "." in email.rsplit("@", 1)[-1]

    def _hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
