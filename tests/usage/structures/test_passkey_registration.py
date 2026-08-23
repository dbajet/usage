from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.passkey_registration import PasskeyRegistration


def test_class() -> None:
    tested = PasskeyRegistration
    fields = ["credential_id", "public_key", "sign_count"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tested = PasskeyRegistration(credential_id="theCredentialId", public_key="thePublicKey", sign_count=7)
    result = tested.to_dict()
    expected = {"credential_id": "theCredentialId", "public_key": "thePublicKey", "sign_count": 7}
    assert result == expected


def test_from_dict() -> None:
    tested = PasskeyRegistration
    tests: list[tuple[dict[str, Any], PasskeyRegistration]] = [
        (
            {"credential_id": "theCredentialId", "public_key": "thePublicKey", "sign_count": 7},
            PasskeyRegistration(credential_id="theCredentialId", public_key="thePublicKey", sign_count=7),
        ),
        (
            {},
            PasskeyRegistration(credential_id="", public_key="", sign_count=0),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
