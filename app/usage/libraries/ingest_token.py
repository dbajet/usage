from __future__ import annotations

import hashlib

from usage.libraries.database import Database
from usage.structures.app_exception import AppException


class IngestToken:
    """The house's push token: what Home Assistant authenticates with.

    Only the hash is ever stored, so the token is shown once when it is minted
    and never again. Two feeds now arrive on it - the thermometers and the
    solar - and the rule about who may write to a house is not something worth
    having two copies of.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def house_id(self, authorization: str) -> int:
        """The house this token belongs to, or a refusal."""
        scheme, _, token = authorization.strip().partition(" ")
        if scheme.lower() != "bearer":
            token = authorization
        token = token.strip()
        if not token:
            raise AppException(401, "A sensor token is required.")
        row = self._database.fetch_one(
            "SELECT id FROM houses WHERE ingest_token_hash = %s AND ingest_token_hash <> ''",
            (self.hashed(token),),
        )
        if row is None:
            raise AppException(401, "The sensor token is not valid.")
        return int(row["id"])

    @classmethod
    def hashed(cls, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
