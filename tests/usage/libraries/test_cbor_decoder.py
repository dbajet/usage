from __future__ import annotations

from typing import Any

import pytest

from usage.libraries.cbor_decoder import CborDecoder
from usage.structures.app_exception import AppException


def helper_instance(data: bytes) -> CborDecoder:
    return CborDecoder(data)


def test___init__() -> None:
    tested = helper_instance(b"\x01\x02")
    expected = b"\x01\x02"
    assert tested._data == expected
    exp_offset = 0
    assert tested._offset == exp_offset


def test_decode() -> None:
    tests: list[tuple[bytes, Any]] = [
        (b"\x00", 0),
        (b"\x17", 23),
        (b"\x18\x18", 24),
        (b"\x19\x01\x00", 256),
        (b"\x1a\x00\x01\x00\x00", 65536),
        (b"\x1b\x00\x00\x00\x01\x00\x00\x00\x00", 4294967296),
        (b"\x20", -1),
        (b"\x38\x63", -100),
        (b"\x43abc", b"abc"),
        (b"\x40", b""),
        (b"\x63foo", "foo"),
        (b"\x82\x01\x02", [1, 2]),
        (b"\x80", []),
        (b"\xa1\x61a\x05", {"a": 5}),
        (b"\xa0", {}),
        (b"\xf4", False),
        (b"\xf5", True),
        (b"\xf6", None),
    ]
    for data, expected in tests:
        tested = helper_instance(data)
        result = tested.decode()
        if expected is None or isinstance(expected, bool):
            assert result is expected, f"---> {data!r}"
        else:
            assert result == expected, f"---> {data!r}"

    error_tests = [
        (b"\xc0\x00", 400, "The passkey payload contains unsupported CBOR data."),
        (b"\xd8\x25", 400, "The passkey payload contains unsupported CBOR data."),
        (b"\xf7", 400, "The passkey payload contains unsupported CBOR data."),
        (b"\x1c", 400, "The passkey payload contains unsupported CBOR data."),
        (b"\x18", 400, "The passkey payload is truncated."),
        (b"", 400, "The passkey payload is truncated."),
    ]
    for data, exp_status_code, exp_message in error_tests:
        tested = helper_instance(data)
        with pytest.raises(AppException) as exc_info:
            tested.decode()
        assert exc_info.value.status_code == exp_status_code, f"---> {data!r}"
        assert exc_info.value.message == exp_message, f"---> {data!r}"


def test__read_item() -> None:
    tests: list[tuple[bytes, Any]] = [
        (b"\x0a", 10),
        (b"\x29", -10),
        (b"\x42hi", b"hi"),
        (b"\x62hi", "hi"),
        (b"\x82\x20\xf5", [-1, True]),
        (b"\xa2\x61a\x01\x61b\x02", {"a": 1, "b": 2}),
        (b"\xf4", False),
        (b"\xf5", True),
        (b"\xf6", None),
    ]
    for data, expected in tests:
        tested = helper_instance(data)
        result = tested._read_item()
        if expected is None or isinstance(expected, bool):
            assert result is expected, f"---> {data!r}"
        else:
            assert result == expected, f"---> {data!r}"

    error_tests = [
        b"\xc2\x41a",  # major type 6 (tag) is unsupported
        b"\xe0",  # major type 7 with an unsupported simple value
        b"\xf8\x20",  # major type 7 with a one-byte simple value
    ]
    for data in error_tests:
        tested = helper_instance(data)
        with pytest.raises(AppException) as exc_info:
            tested._read_item()
        exp_status_code = 400
        exp_message = "The passkey payload contains unsupported CBOR data."
        assert exc_info.value.status_code == exp_status_code, f"---> {data!r}"
        assert exc_info.value.message == exp_message, f"---> {data!r}"


def test__read_head() -> None:
    tests = [
        (b"\x05", (0, 5)),
        (b"\x18\xff", (0, 255)),
        (b"\x19\x12\x34", (0, 4660)),
        (b"\x1a\x12\x34\x56\x78", (0, 305419896)),
        (b"\x1b\x00\x00\x00\x00\x12\x34\x56\x78", (0, 305419896)),
        (b"\x45", (2, 5)),
        (b"\xa3", (5, 3)),
    ]
    for data, expected in tests:
        tested = helper_instance(data)
        result = tested._read_head()
        assert result == expected, f"---> {data!r}"

    error_tests = [
        b"\x1c",  # additional info 28 is unsupported
        b"\x1d",  # additional info 29 is unsupported
        b"\x1f",  # additional info 31 (indefinite length) is unsupported
    ]
    for data in error_tests:
        tested = helper_instance(data)
        with pytest.raises(AppException) as exc_info:
            tested._read_head()
        exp_status_code = 400
        exp_message = "The passkey payload contains unsupported CBOR data."
        assert exc_info.value.status_code == exp_status_code, f"---> {data!r}"
        assert exc_info.value.message == exp_message, f"---> {data!r}"


def test__read_bytes() -> None:
    tested = helper_instance(b"abcdef")
    result = tested._read_bytes(2)
    expected = b"ab"
    assert result == expected
    result = tested._read_bytes(3)
    expected = b"cde"
    assert result == expected

    with pytest.raises(AppException) as exc_info:
        tested._read_bytes(2)
    exp_status_code = 400
    exp_message = "The passkey payload is truncated."
    assert exc_info.value.status_code == exp_status_code
    assert exc_info.value.message == exp_message
