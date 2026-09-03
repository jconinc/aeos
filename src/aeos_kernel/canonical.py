"""Strict canonical JSON and stable identity helpers.

Derived from MultiAgentCommunication's decision-engine fingerprint contract at
d1047fb62d6fd6cba91fe262e8a9d3ddc9259bff. AEOS deliberately tightens the source
helper by rejecting non-JSON values and NaN instead of coercing them with ``str``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize a strict JSON value in the one AEOS canonical form.

    The round trip catches tuples, integer dictionary keys, and custom mapping
    implementations whose shape JSON would otherwise silently change.
    """

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    decoded = json.loads(encoded)
    if decoded != value:
        raise TypeError("value does not survive a strict JSON round trip")
    return encoded


def stable_fingerprint(value: Any) -> str:
    """Return the lowercase SHA-256 digest of canonical strict JSON."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_digest(data: bytes) -> str:
    """Return a full lowercase SHA-256 content digest."""

    return hashlib.sha256(data).hexdigest()


def without_keys(value: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    """Return a plain dictionary without the named self-referential fields."""

    omitted = frozenset(keys)
    return {key: item for key, item in value.items() if key not in omitted}
