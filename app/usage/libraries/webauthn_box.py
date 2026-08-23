from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from usage.libraries.cbor_decoder import CborDecoder
from usage.structures.app_exception import AppException
from usage.structures.passkey_registration import PasskeyRegistration


class WebauthnBox:
    """Parses and verifies WebAuthn payloads (registration and assertion)."""

    @classmethod
    def encode_base64url(cls, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")

    @classmethod
    def decode_base64url(cls, value: str) -> bytes:
        padded = value + "=" * (-len(value) % 4)
        try:
            return base64.urlsafe_b64decode(padded.encode("utf-8"))
        except (ValueError, TypeError) as exception:
            raise AppException(400, "The passkey payload is not valid base64url.") from exception

    @classmethod
    def parse_attestation(cls, attestation_object: str, rp_id: str) -> PasskeyRegistration:
        decoded = CborDecoder(cls.decode_base64url(attestation_object)).decode()
        if not isinstance(decoded, dict) or not isinstance(decoded.get("authData"), bytes):
            raise AppException(400, "The passkey attestation is malformed.")
        auth_data = decoded["authData"]
        cls._check_auth_data(auth_data, rp_id, require_credential=True)
        credential_length = int.from_bytes(auth_data[53:55], "big")
        credential_end = 55 + credential_length
        if credential_end > len(auth_data):
            raise AppException(400, "The passkey attestation is truncated.")
        return PasskeyRegistration(
            credential_id=cls.encode_base64url(auth_data[55:credential_end]),
            public_key=cls.encode_base64url(auth_data[credential_end:]),
            sign_count=int.from_bytes(auth_data[33:37], "big"),
        )

    @classmethod
    def verify_assertion(
        cls,
        public_key: str,
        authenticator_data: bytes,
        client_data: bytes,
        signature: bytes,
        rp_id: str,
    ) -> int:
        """Verifies the assertion signature and returns the new sign count."""
        cls._check_auth_data(authenticator_data, rp_id, require_credential=False)
        signed = authenticator_data + hashlib.sha256(client_data).digest()
        cose = CborDecoder(cls.decode_base64url(public_key)).decode()
        if not isinstance(cose, dict):
            raise AppException(400, "The stored passkey public key is malformed.")
        try:
            cls._verify_cose_signature(cose, signed, signature)
        except InvalidSignature as exception:
            raise AppException(401, "The passkey signature is invalid.") from exception
        return int.from_bytes(authenticator_data[33:37], "big")

    @classmethod
    def _verify_cose_signature(cls, cose: dict[int, object], signed: bytes, signature: bytes) -> None:
        key_type = cose.get(1)
        if key_type == 2:  # EC2 / ES256 on P-256
            x_bytes = cose.get(-2)
            y_bytes = cose.get(-3)
            if not isinstance(x_bytes, bytes) or not isinstance(y_bytes, bytes):
                raise AppException(400, "The stored passkey public key is malformed.")
            numbers = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x_bytes, "big"),
                int.from_bytes(y_bytes, "big"),
                ec.SECP256R1(),
            )
            numbers.public_key().verify(signature, signed, ec.ECDSA(hashes.SHA256()))
            return
        if key_type == 3:  # RSA / RS256
            modulus = cose.get(-1)
            exponent = cose.get(-2)
            if not isinstance(modulus, bytes) or not isinstance(exponent, bytes):
                raise AppException(400, "The stored passkey public key is malformed.")
            rsa_numbers = rsa.RSAPublicNumbers(
                int.from_bytes(exponent, "big"),
                int.from_bytes(modulus, "big"),
            )
            rsa_numbers.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
            return
        raise AppException(400, "The passkey uses an unsupported key type.")

    @classmethod
    def _check_auth_data(cls, auth_data: bytes, rp_id: str, require_credential: bool) -> None:
        if len(auth_data) < 37:
            raise AppException(400, "The passkey authenticator data is truncated.")
        if auth_data[:32] != hashlib.sha256(rp_id.encode("utf-8")).digest():
            raise AppException(400, "The passkey does not belong to this site.")
        flags = auth_data[32]
        if not flags & 0x01:
            raise AppException(401, "The passkey ceremony did not confirm user presence.")
        if require_credential and not flags & 0x40:
            raise AppException(400, "The passkey attestation carries no credential.")
