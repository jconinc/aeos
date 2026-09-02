"""Shared strict validation helpers for public contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError

DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class FrozenDict(dict[str, Any]):
    """A JSON object that remains serializable but cannot change after construction."""

    def __init__(self, value: Mapping[str, Any]) -> None:
        dict.__init__(self, ((str(key), freeze_json(item)) for key, item in value.items()))

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("AEOS contract JSON is immutable")

    __delitem__ = _immutable
    __ior__ = _immutable  # type: ignore[assignment]
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable
    update = _immutable

    def __copy__(self) -> FrozenDict:
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> FrozenDict:
        return self


class FrozenList(list[Any]):
    """A JSON array that remains serializable but cannot change after construction."""

    def __init__(self, value: list[Any]) -> None:
        list.__init__(self, (freeze_json(item) for item in value))

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("AEOS contract JSON is immutable")

    __delitem__ = _immutable
    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]
    __setitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __copy__(self) -> FrozenList:
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> FrozenList:
        return self


def freeze_json(value: Any) -> Any:
    """Deep-freeze one already validated strict JSON value."""

    if isinstance(value, FrozenDict | FrozenList):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, list):
        return FrozenList(value)
    return deepcopy(value)


def immutable_json_object(value: Mapping[str, Any], field_name: str) -> FrozenDict:
    """Validate and deeply freeze one public JSON-object field."""

    try:
        stable_fingerprint(value)
    except (TypeError, ValueError) as error:
        raise ContractError(f"{field_name} must be a strict JSON object") from error
    return FrozenDict(value)


def thaw_json(value: Any) -> Any:
    """Return ordinary mutable JSON containers for interchange serialization."""

    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [thaw_json(item) for item in value]
    return deepcopy(value)


def required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError(f"{field_name} must be a clean nonempty string")
    if any(not char.isprintable() for char in value):
        raise ContractError(f"{field_name} contains control characters")
    return value


def digest(value: str, field_name: str) -> str:
    if not DIGEST_PATTERN.fullmatch(value):
        raise ContractError(f"{field_name} must be a full lowercase SHA-256 digest")
    return value


def utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value
