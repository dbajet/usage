from __future__ import annotations

import pytest

from usage.libraries.crypto_box import CryptoBox
from usage.structures.app_exception import AppException


def helper_instance() -> CryptoBox:
    return CryptoBox("test-key")


def test___init__() -> None:
    tested = CryptoBox
    with pytest.raises(AppException) as exc_info:
        tested("")
    exp_status_code = 500
    exp_message = "USAGE_ENCRYPTION_KEY is required."
    assert exc_info.value.status_code == exp_status_code
    assert exc_info.value.message == exp_message

    result = tested("test-key")
    expected = b"test-key"
    assert result._raw_key == expected


def test_encrypt() -> None:
    tested = helper_instance()
    result = tested.encrypt("")
    expected = ""
    assert result == expected

    result = tested.encrypt("the secret value")
    assert result != "the secret value"
    decrypted = tested.decrypt(result)
    expected = "the secret value"
    assert decrypted == expected


def test_decrypt() -> None:
    tested = helper_instance()
    result = tested.decrypt("")
    expected = ""
    assert result == expected

    encrypted = tested.encrypt("the secret value")
    result = tested.decrypt(encrypted)
    expected = "the secret value"
    assert result == expected

    with pytest.raises(AppException) as exc_info:
        tested.decrypt("not-a-valid-token")
    exp_status_code = 500
    exp_message = "Encrypted data could not be decrypted with the configured key."
    assert exc_info.value.status_code == exp_status_code
    assert exc_info.value.message == exp_message


def test_blind_index() -> None:
    tested = helper_instance()
    tests = [
        ("  Alice@Example.COM ", "f4ec100211f13d19d596a3b4a8d60f6a5ccf3d3a3c3c9fece41d1ff21e5475dd"),
        ("alice@example.com", "f4ec100211f13d19d596a3b4a8d60f6a5ccf3d3a3c3c9fece41d1ff21e5475dd"),
        ("", "2711cc23e9ab1b8a9bc0fe991238da92671624a9ebdaf1c1abec06e7e9a14f9b"),
    ]
    for value, expected in tests:
        result = tested.blind_index(value)
        assert result == expected, f"---> {value}"


def test__normalize_key() -> None:
    tested = helper_instance()
    tests = [
        ("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=", b"MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="),
        ("passphrase", b"HgiePFMjrYCpB2e91ZByl7QTgWPwJwl_072-q1KNLWg="),
        ("dG9vLXNob3J0", b"5txARj9CZQIhsnB7_bEYNavcJ0WSTiQG9F7zniK-tdU="),
    ]
    for encryption_key, expected in tests:
        result = tested._normalize_key(encryption_key)
        assert result == expected, f"---> {encryption_key}"
