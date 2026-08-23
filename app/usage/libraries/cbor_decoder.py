from __future__ import annotations

from typing import Any

from usage.structures.app_exception import AppException


class CborDecoder:
    """Minimal CBOR decoder covering the subset used by WebAuthn payloads.

    Supports unsigned/negative integers, byte strings, text strings, arrays,
    maps, booleans, and null. Anything else raises, which is fine: WebAuthn
    attestation objects and COSE keys use nothing more.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def decode(self) -> Any:
        return self._read_item()

    def _read_item(self) -> Any:
        major, argument = self._read_head()
        if major == 0:
            return argument
        if major == 1:
            return -1 - argument
        if major == 2:
            return self._read_bytes(argument)
        if major == 3:
            return self._read_bytes(argument).decode("utf-8")
        if major == 4:
            return [self._read_item() for _ in range(argument)]
        if major == 5:
            return {self._read_item(): self._read_item() for _ in range(argument)}
        if major == 7:
            if argument == 20:
                return False
            if argument == 21:
                return True
            if argument == 22:
                return None
        raise AppException(400, "The passkey payload contains unsupported CBOR data.")

    def _read_head(self) -> tuple[int, int]:
        first = self._read_bytes(1)[0]
        major = first >> 5
        info = first & 0x1F
        if info < 24:
            return major, info
        if info == 24:
            return major, self._read_bytes(1)[0]
        if info == 25:
            return major, int.from_bytes(self._read_bytes(2), "big")
        if info == 26:
            return major, int.from_bytes(self._read_bytes(4), "big")
        if info == 27:
            return major, int.from_bytes(self._read_bytes(8), "big")
        raise AppException(400, "The passkey payload contains unsupported CBOR data.")

    def _read_bytes(self, length: int) -> bytes:
        if self._offset + length > len(self._data):
            raise AppException(400, "The passkey payload is truncated.")
        result = self._data[self._offset:self._offset + length]
        self._offset += length
        return result
