from __future__ import annotations

import dataclasses
from typing import Any


def is_namedtuple(tested: Any, fields: list[str]) -> bool:
    return (
        issubclass(tested, tuple)
        and hasattr(tested, "_fields")
        and list(tested._fields) == fields
    )


def is_dataclass(tested: Any, fields: list[str]) -> bool:
    return (
        dataclasses.is_dataclass(tested)
        and [field.name for field in dataclasses.fields(tested)] == fields
    )
