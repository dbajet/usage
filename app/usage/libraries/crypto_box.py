from __future__ import annotations

import base64
import binascii
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from usage.structures.app_exception import AppException


class CryptoBox:
    def __init__(self, encryption_key: str) -> None:
        if not encryption_key:
            raise AppException(500, "USAGE_ENCRYPTION_KEY is required.")
        self._raw_key = encryption_key.encode("utf-8")
        self._fernet = Fernet(self._normalize_key(encryption_key))

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            result = self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exception:
            raise AppException(500, "Encrypted data could not be decrypted with the configured key.") from exception
        return result

    def blind_index(self, value: str) -> str:
        normalized = value.strip().lower()
        return hmac.new(self._raw_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    def _normalize_key(self, encryption_key: str) -> bytes:
        try:
            decoded = base64.b64decode(encryption_key.encode("utf-8"), altchars=b"-_", validate=True)
            if len(decoded) == 32:
                return encryption_key.encode("utf-8")
        except (binascii.Error, ValueError):
            pass
        digest = hashlib.sha256(encryption_key.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)
