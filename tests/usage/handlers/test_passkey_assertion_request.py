from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.passkey_assertion_request import PasskeyAssertionRequest


def test_inheritance() -> None:
    tested = PasskeyAssertionRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = PasskeyAssertionRequest
    result = list(tested.model_fields.keys())
    expected = ["credential_id", "authenticator_data", "client_data", "signature"]
    assert result == expected


def test___init__() -> None:
    tested = PasskeyAssertionRequest(
        credential_id="theCredentialId",
        authenticator_data="theAuthenticatorData",
        client_data="theClientData",
        signature="theSignature",
    )
    result = tested.model_dump()
    expected = {
        "credential_id": "theCredentialId",
        "authenticator_data": "theAuthenticatorData",
        "client_data": "theClientData",
        "signature": "theSignature",
    }
    assert result == expected
