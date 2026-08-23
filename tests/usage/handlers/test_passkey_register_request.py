from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.passkey_register_request import PasskeyRegisterRequest


def test_inheritance() -> None:
    tested = PasskeyRegisterRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = PasskeyRegisterRequest
    result = list(tested.model_fields.keys())
    expected = ["credential_id", "attestation_object", "client_data"]
    assert result == expected


def test___init__() -> None:
    tested = PasskeyRegisterRequest(
        credential_id="theCredentialId",
        attestation_object="theAttestation",
        client_data="theClientData",
    )
    result = tested.model_dump()
    expected = {
        "credential_id": "theCredentialId",
        "attestation_object": "theAttestation",
        "client_data": "theClientData",
    }
    assert result == expected
