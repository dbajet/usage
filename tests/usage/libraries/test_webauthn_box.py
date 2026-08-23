from __future__ import annotations

import hashlib
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from usage.libraries.webauthn_box import WebauthnBox
from usage.structures.app_exception import AppException
from usage.structures.passkey_registration import PasskeyRegistration


def helper_cbor_head(major: int, argument: int) -> bytes:
    if argument < 24:
        return bytes([(major << 5) | argument])
    if argument < 256:
        return bytes([(major << 5) | 24, argument])
    return bytes([(major << 5) | 25]) + argument.to_bytes(2, "big")


def helper_cbor_encode(value: Any) -> bytes:
    if isinstance(value, int):
        if value < 0:
            return helper_cbor_head(1, -1 - value)
        return helper_cbor_head(0, value)
    if isinstance(value, bytes):
        return helper_cbor_head(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return helper_cbor_head(3, len(encoded)) + encoded
    if isinstance(value, list):
        return helper_cbor_head(4, len(value)) + b"".join(helper_cbor_encode(item) for item in value)
    assert isinstance(value, dict)
    return helper_cbor_head(5, len(value)) + b"".join(
        helper_cbor_encode(key) + helper_cbor_encode(item) for key, item in value.items()
    )


def helper_auth_data(rp_id: str, flags: int, sign_count: int, credential: bytes = b"") -> bytes:
    return hashlib.sha256(rp_id.encode("utf-8")).digest() + bytes([flags]) + sign_count.to_bytes(4, "big") + credential


def helper_ec_cose(private_key: ec.EllipticCurvePrivateKey) -> dict[int, bytes | int]:
    numbers = private_key.public_key().public_numbers()
    return {1: 2, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}


def helper_rsa_cose(private_key: rsa.RSAPrivateKey) -> dict[int, bytes | int]:
    numbers = private_key.public_key().public_numbers()
    return {1: 3, -1: numbers.n.to_bytes(256, "big"), -2: numbers.e.to_bytes(3, "big")}


def test_encode_base64url() -> None:
    tested = WebauthnBox
    tests = [
        (b"hello", "aGVsbG8"),
        (b"\xfb\xef\xff", "--__"),
        (b"", ""),
    ]
    for value, expected in tests:
        result = tested.encode_base64url(value)
        assert result == expected, f"---> {value!r}"


def test_decode_base64url() -> None:
    tested = WebauthnBox
    tests = [
        ("aGVsbG8", b"hello"),
        ("--__", b"\xfb\xef\xff"),
        ("", b""),
    ]
    for value, expected in tests:
        result = tested.decode_base64url(value)
        assert result == expected, f"---> {value}"

    with pytest.raises(AppException) as exc_info:
        tested.decode_base64url("a")
    exp_status_code = 400
    exp_message = "The passkey payload is not valid base64url."
    assert exc_info.value.status_code == exp_status_code
    assert exc_info.value.message == exp_message


def test_parse_attestation() -> None:
    tested = WebauthnBox
    # the decoded CBOR is not a dict
    malformed_tests = [
        tested.encode_base64url(helper_cbor_encode([1, 2])),
        tested.encode_base64url(helper_cbor_encode({"authData": "not-bytes"})),
        tested.encode_base64url(helper_cbor_encode({"fmt": "none"})),
    ]
    for attestation_object in malformed_tests:
        with pytest.raises(AppException) as exc_info:
            tested.parse_attestation(attestation_object, "example.org")
        exp_status_code = 400
        exp_message = "The passkey attestation is malformed."
        assert exc_info.value.status_code == exp_status_code, f"---> {attestation_object}"
        assert exc_info.value.message == exp_message, f"---> {attestation_object}"

    # happy path: aaguid + credential id length + credential id + cose key
    credential = bytes(16) + len(b"credential-id").to_bytes(2, "big") + b"credential-id" + b"cose-public-key"
    auth_data = helper_auth_data("example.org", 0x41, 7, credential)
    attestation_object = tested.encode_base64url(helper_cbor_encode({"authData": auth_data}))
    result = tested.parse_attestation(attestation_object, "example.org")
    expected = PasskeyRegistration(
        credential_id="Y3JlZGVudGlhbC1pZA",
        public_key="Y29zZS1wdWJsaWMta2V5",
        sign_count=7,
    )
    assert result == expected

    # the declared credential length exceeds the available bytes
    truncated = bytes(16) + (500).to_bytes(2, "big") + b"credential-id"
    auth_data = helper_auth_data("example.org", 0x41, 7, truncated)
    attestation_object = tested.encode_base64url(helper_cbor_encode({"authData": auth_data}))
    with pytest.raises(AppException) as exc_info:
        tested.parse_attestation(attestation_object, "example.org")
    exp_status_code = 400
    exp_message = "The passkey attestation is truncated."
    assert exc_info.value.status_code == exp_status_code
    assert exc_info.value.message == exp_message


def test_verify_assertion() -> None:
    tested = WebauthnBox
    client_data = b'{"type":"webauthn.get"}'

    # happy path with an EC P-256 key
    ec_key = ec.generate_private_key(ec.SECP256R1())
    public_key = tested.encode_base64url(helper_cbor_encode(helper_ec_cose(ec_key)))
    authenticator_data = helper_auth_data("example.org", 0x01, 9)
    signed = authenticator_data + hashlib.sha256(client_data).digest()
    signature = ec_key.sign(signed, ec.ECDSA(hashes.SHA256()))
    result = tested.verify_assertion(public_key, authenticator_data, client_data, signature, "example.org")
    expected = 9
    assert result == expected

    # happy path with an RSA key
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = tested.encode_base64url(helper_cbor_encode(helper_rsa_cose(rsa_key)))
    authenticator_data = helper_auth_data("example.org", 0x01, 4660)
    signed = authenticator_data + hashlib.sha256(client_data).digest()
    signature = rsa_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    result = tested.verify_assertion(public_key, authenticator_data, client_data, signature, "example.org")
    expected = 4660
    assert result == expected

    # the stored public key is not a CBOR dict
    public_key = tested.encode_base64url(helper_cbor_encode([1, 2]))
    authenticator_data = helper_auth_data("example.org", 0x01, 9)
    with pytest.raises(AppException) as exc_info:
        tested.verify_assertion(public_key, authenticator_data, client_data, b"signature", "example.org")
    exp_status_code = 400
    exp_message = "The stored passkey public key is malformed."
    assert exc_info.value.status_code == exp_status_code
    assert exc_info.value.message == exp_message

    # the signature does not match
    public_key = tested.encode_base64url(helper_cbor_encode(helper_ec_cose(ec_key)))
    authenticator_data = helper_auth_data("example.org", 0x01, 9)
    other_signed = authenticator_data + hashlib.sha256(b"other-client-data").digest()
    signature = ec_key.sign(other_signed, ec.ECDSA(hashes.SHA256()))
    with pytest.raises(AppException) as exc_info:
        tested.verify_assertion(public_key, authenticator_data, client_data, signature, "example.org")
    exp_status_code = 401
    exp_message = "The passkey signature is invalid."
    assert exc_info.value.status_code == exp_status_code
    assert exc_info.value.message == exp_message


def test__verify_cose_signature() -> None:
    tested = WebauthnBox
    signed = b"the signed payload"

    # valid EC signature
    ec_key = ec.generate_private_key(ec.SECP256R1())
    signature = ec_key.sign(signed, ec.ECDSA(hashes.SHA256()))
    result = tested._verify_cose_signature(helper_ec_cose(ec_key), signed, signature)
    assert result is None

    # valid RSA signature
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signature = rsa_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    result = tested._verify_cose_signature(helper_rsa_cose(rsa_key), signed, signature)
    assert result is None

    # malformed or unsupported COSE keys
    error_tests: list[tuple[dict[int, Any], int, str]] = [
        ({1: 2, -2: "not-bytes", -3: bytes(32)}, 400, "The stored passkey public key is malformed."),
        ({1: 2, -2: bytes(32)}, 400, "The stored passkey public key is malformed."),
        ({1: 3, -1: "not-bytes", -2: bytes(3)}, 400, "The stored passkey public key is malformed."),
        ({1: 3, -1: bytes(256)}, 400, "The stored passkey public key is malformed."),
        ({1: 99}, 400, "The passkey uses an unsupported key type."),
        ({}, 400, "The passkey uses an unsupported key type."),
    ]
    for cose, exp_status_code, exp_message in error_tests:
        with pytest.raises(AppException) as exc_info:
            tested._verify_cose_signature(cose, signed, b"signature")
        assert exc_info.value.status_code == exp_status_code, f"---> {cose}"
        assert exc_info.value.message == exp_message, f"---> {cose}"


def test__check_auth_data() -> None:
    tested = WebauthnBox

    # valid without and with a credential requirement
    result = tested._check_auth_data(helper_auth_data("example.org", 0x01, 1), "example.org", False)
    assert result is None
    result = tested._check_auth_data(helper_auth_data("example.org", 0x41, 1), "example.org", True)
    assert result is None

    error_tests = [
        (b"\x00" * 36, "example.org", False, 400, "The passkey authenticator data is truncated."),
        (b"", "example.org", False, 400, "The passkey authenticator data is truncated."),
        (helper_auth_data("other.org", 0x01, 1), "example.org", False, 400, "The passkey does not belong to this site."),
        (helper_auth_data("example.org", 0x40, 1), "example.org", False, 401, "The passkey ceremony did not confirm user presence."),
        (helper_auth_data("example.org", 0x00, 1), "example.org", False, 401, "The passkey ceremony did not confirm user presence."),
        (helper_auth_data("example.org", 0x01, 1), "example.org", True, 400, "The passkey attestation carries no credential."),
    ]
    for auth_data, rp_id, require_credential, exp_status_code, exp_message in error_tests:
        with pytest.raises(AppException) as exc_info:
            tested._check_auth_data(auth_data, rp_id, require_credential)
        assert exc_info.value.status_code == exp_status_code, f"---> {auth_data!r}"
        assert exc_info.value.message == exp_message, f"---> {auth_data!r}"
