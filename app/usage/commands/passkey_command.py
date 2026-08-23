from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.webauthn_box import WebauthnBox
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


class PasskeyCommand:
    def __init__(self, database: Database) -> None:
        self._database = database

    def registration_options(self, user: SessionUser, rp_id: str) -> tuple[dict[str, Any], str]:
        challenge = WebauthnBox.encode_base64url(secrets.token_bytes(32))
        existing = self._database.fetch_all(
            "SELECT credential_id FROM passkeys WHERE user_id = %s ORDER BY id",
            (user.user_id,),
        )
        options = {
            "rp_id": rp_id,
            "rp_name": Constants.app_name,
            "user_id": WebauthnBox.encode_base64url(str(user.user_id).encode("utf-8")),
            "user_name": user.email,
            "user_display_name": user.name or user.email,
            "challenge": challenge,
            "exclude_credentials": [str(row["credential_id"]) for row in existing],
        }
        return options, self._challenge_token("register", challenge, user.user_id)

    def register(self, user: SessionUser, data: dict[str, Any], challenge_token: str, rp_id: str) -> dict[str, str]:
        payload = self._challenge_payload(challenge_token, "register")
        if int(payload.get("user_id") or 0) != user.user_id:
            raise AppException(400, "The passkey challenge does not belong to this account.")
        client_data = self._client_data(str(data.get("client_data") or ""), "webauthn.create", str(payload["challenge"]), rp_id)
        registration = WebauthnBox.parse_attestation(str(data.get("attestation_object") or ""), rp_id)
        if registration.credential_id != str(data.get("credential_id") or ""):
            raise AppException(400, "The passkey credential does not match its attestation.")
        del client_data  # validated above; nothing else to read from it
        inserted = self._database.execute(
            """
            INSERT INTO passkeys(user_id, credential_id, public_key, sign_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (credential_id) DO NOTHING
            RETURNING id
            """,
            (user.user_id, registration.credential_id, registration.public_key, registration.sign_count),
        )
        if not inserted:
            raise AppException(409, "This passkey is already registered.")
        return {"message": "Passkey registered."}

    def list_passkeys(self, user: SessionUser) -> list[dict[str, Any]]:
        return self._database.fetch_all(
            "SELECT id, created_at, last_used_at FROM passkeys WHERE user_id = %s ORDER BY created_at",
            (user.user_id,),
        )

    def delete_passkey(self, user: SessionUser, passkey_id: int) -> dict[str, str]:
        row = self._database.fetch_one(
            "SELECT id FROM passkeys WHERE id = %s AND user_id = %s",
            (passkey_id, user.user_id),
        )
        if row is None:
            raise AppException(404, "The passkey was not found.")
        self._database.execute("DELETE FROM passkeys WHERE id = %s", (passkey_id,))
        return {"message": "Passkey removed."}

    def authentication_options(self, email: str, rp_id: str) -> tuple[dict[str, Any], str]:
        email_hash = self._database.blind_index(email.strip().lower())
        user = self._database.fetch_one("SELECT id FROM users WHERE email_hash = %s", (email_hash,))
        credentials: list[str] = []
        if user is not None:
            rows = self._database.fetch_all(
                "SELECT credential_id FROM passkeys WHERE user_id = %s ORDER BY id",
                (int(user["id"]),),
            )
            credentials = [str(row["credential_id"]) for row in rows]
        if not credentials:
            raise AppException(404, "No passkey is registered for this email.")
        challenge = WebauthnBox.encode_base64url(secrets.token_bytes(32))
        options = {
            "rp_id": rp_id,
            "challenge": challenge,
            "allow_credentials": credentials,
        }
        return options, self._challenge_token("auth", challenge, int(user["id"]) if user else 0)

    def verify_authentication(self, data: dict[str, Any], challenge_token: str, rp_id: str) -> str:
        payload = self._challenge_payload(challenge_token, "auth")
        user_id = int(payload.get("user_id") or 0)
        credential_id = str(data.get("credential_id") or "")
        passkey = self._database.fetch_one(
            "SELECT id, public_key, sign_count FROM passkeys WHERE credential_id = %s AND user_id = %s",
            (credential_id, user_id),
        )
        if passkey is None:
            raise AppException(401, "The passkey is not registered for this account.")
        client_data_raw = str(data.get("client_data") or "")
        self._client_data(client_data_raw, "webauthn.get", str(payload["challenge"]), rp_id)
        sign_count = WebauthnBox.verify_assertion(
            str(passkey["public_key"]),
            WebauthnBox.decode_base64url(str(data.get("authenticator_data") or "")),
            WebauthnBox.decode_base64url(client_data_raw),
            WebauthnBox.decode_base64url(str(data.get("signature") or "")),
            rp_id,
        )
        result = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + timedelta(days=Constants.session_days)).isoformat()
        with self._database.transaction():
            self._database.execute(
                "UPDATE passkeys SET sign_count = %s, last_used_at = now() WHERE id = %s",
                (sign_count, passkey["id"]),
            )
            self._database.execute(
                "INSERT INTO sessions(user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (user_id, self._hash(result), expires_at),
            )
            self._database.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
        return result

    def _client_data(
        self,
        client_data_encoded: str,
        expected_type: str,
        expected_challenge: str,
        rp_id: str,
    ) -> dict[str, Any]:
        try:
            result = json.loads(WebauthnBox.decode_base64url(client_data_encoded).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exception:
            raise AppException(400, "The passkey client data is malformed.") from exception
        if result.get("type") != expected_type:
            raise AppException(400, "The passkey ceremony type is unexpected.")
        if result.get("challenge") != expected_challenge:
            raise AppException(400, "The passkey challenge does not match.")
        hostname = urlparse(str(result.get("origin") or "")).hostname or ""
        if hostname != rp_id and not hostname.endswith(f".{rp_id}"):
            raise AppException(400, "The passkey origin does not match this site.")
        return dict(result)

    def _challenge_token(self, purpose: str, challenge: str, user_id: int) -> str:
        expires_at = (datetime.now(UTC) + timedelta(minutes=Constants.webauthn_challenge_minutes)).isoformat()
        return self._database.encrypt(json.dumps({
            "purpose": purpose,
            "challenge": challenge,
            "user_id": user_id,
            "expires_at": expires_at,
        }))

    def _challenge_payload(self, challenge_token: str, purpose: str) -> dict[str, Any]:
        if not challenge_token:
            raise AppException(400, "The passkey challenge is missing. Start again.")
        try:
            result = json.loads(self._database.decrypt(challenge_token))
        except (ValueError, AppException) as exception:
            raise AppException(400, "The passkey challenge is invalid. Start again.") from exception
        if result.get("purpose") != purpose:
            raise AppException(400, "The passkey challenge is invalid. Start again.")
        expires_at = datetime.fromisoformat(str(result.get("expires_at") or datetime.now(UTC).isoformat()))
        if expires_at < datetime.now(UTC):
            raise AppException(400, "The passkey challenge has expired. Start again.")
        return dict(result)

    def _hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
