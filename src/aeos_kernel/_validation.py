"""Shared strict validation helpers for public contracts."""

from __future__ import annotations

import re
from datetime import datetime

from aeos_kernel.errors import ContractError

DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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
