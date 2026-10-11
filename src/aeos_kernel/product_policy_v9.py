"""Manifest v9: an approved probe spending limit of zero.

v9 composes the immutable v8 manifest. The four money keys of ``authority.probe_budget``
accept the minor-unit amount ``"0"`` (approved: free checks only) as well as positive amounts.
Everything else is v8's: ``window_days`` is a positive integer, null means not approved, all
five keys are null or all are set, and the ceilings stay ordered. v8 still refuses ``"0"``;
because the meaning of ``"0"`` changes, v9 is a new schema version with its own capability.

The daily count cap is not a kernel key: the host counts the approved manifest's existing
``authority.target_query_classes``. Parsing never approves a value or grants spending authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from typing import Any, Final, cast
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    READER_CAPABILITIES,
    ManifestReason,
    _fail,
    _object,
    _positive,
    _section,
    _serialize,
    _version_key,
    canonical_integer_string,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v2 import READER_CAPABILITIES_V2
from aeos_kernel.product_policy_v3 import READER_CAPABILITIES_V3
from aeos_kernel.product_policy_v4 import READER_CAPABILITIES_V4
from aeos_kernel.product_policy_v5 import READER_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import READER_CAPABILITIES_V6
from aeos_kernel.product_policy_v7 import READER_CAPABILITIES_V7
from aeos_kernel.product_policy_v8 import (
    PROBE_SPENDING_KEYS,
    READER_CAPABILITIES_V8,
    SCHEMA_VERSION_V8,
    CanonicalProductManifestV8,
    normalize_manifest_payload_v8,
    policy_leaf_paths_v8,
    purpose_principal_classes_v8,
    section_authority_classes_v8,
    section_paths_v8,
)

SCHEMA_VERSION_V9: Final = "aeos.product-manifest.v9"
READER_VERSION_V9: Final = "9.0.0"
READER_CAPABILITIES_V9: Final = frozenset(
    {
        SCHEMA_VERSION_V9,
        "canonical_manifest_bytes_v9",
        "authority_probe_spending_v2",
    }
)
#: The four money keys that accept "0" from v9. ``window_days`` stays positive.
PROBE_MONEY_KEYS: Final = PROBE_SPENDING_KEYS[1:]


def section_authority_classes_v9(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v8(profile)


def section_paths_v9(profile: str) -> Mapping[str, tuple[str, ...]]:
    return section_paths_v8(profile)


def purpose_principal_classes_v9(profile: str) -> Mapping[str, str]:
    return purpose_principal_classes_v8(profile)


def _minor(value: Any, path: str) -> str:
    return canonical_integer_string(value, path, signed=False)


_PROBE_SPENDING = _object(
    {"window_days": _positive, **dict.fromkeys(PROBE_MONEY_KEYS, _minor)},
    nullable=frozenset(PROBE_SPENDING_KEYS),
)


def normalize_probe_spending_v2(
    value: Mapping[str, Any], path: str = "manifest.authority.probe_budget"
) -> dict[str, Any]:
    """All five keys null (not approved) or all set; money may be "0"; ceilings ordered."""

    row = _PROBE_SPENDING(value, path)
    unset = [key for key in PROBE_SPENDING_KEYS if row[key] is None]
    if unset and len(unset) != len(PROBE_SPENDING_KEYS):
        _fail(f"{path}.{unset[0]}", "is null while other spending limits are set")
    if not unset:
        per_call, window, daily, monthly = (int(row[key]) for key in PROBE_MONEY_KEYS)
        if per_call > window:
            _fail(f"{path}.per_call_ceiling_minor", "exceeds window_ceiling_minor")
        if per_call > daily:
            _fail(f"{path}.per_call_ceiling_minor", "exceeds daily_ceiling_minor")
        if daily > monthly:
            _fail(f"{path}.daily_ceiling_minor", "exceeds monthly_ceiling_minor")
    return dict(row)


def normalize_manifest_payload_v9(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V9:
        _fail("manifest.schema_version", "is not a v9 schema", ManifestReason.INCOMPATIBLE)
    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        _fail("manifest.authority", "must be an object")
    authority = cast(Mapping[str, Any], authority)
    budget = authority.get("probe_budget")
    if not isinstance(budget, Mapping):
        _fail("manifest.authority.probe_budget", "must be an object")
    budget = cast(Mapping[str, Any], budget)
    spending = normalize_probe_spending_v2(
        {key: item for key, item in budget.items() if key in PROBE_SPENDING_KEYS}
    )
    # v8 owns every other rule and refuses "0", so it reads the spending group as not approved.
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V8
    prior["authority"] = {
        **authority,
        "probe_budget": {**budget, **dict.fromkeys(PROBE_SPENDING_KEYS)},
    }
    normalized = normalize_manifest_payload_v8(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V9:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v9 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V9
    normalized["authority"]["probe_budget"].update(spending)
    return normalized


class CanonicalProductManifestV9(CanonicalProductManifestV8):
    """V9 lets the four probe spending ceilings be an approved 0."""

    @property
    def probe_spending(self) -> dict[str, Any]:
        """The five limits as an independent object; all None while not approved."""

        budget = self.payload["authority"]["probe_budget"]
        return normalize_probe_spending_v2({key: budget[key] for key in PROBE_SPENDING_KEYS})

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V9,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        compatibility = self.payload["compatibility"]
        version = _version_key(reader_version)
        prior = (READER_CAPABILITIES_V2 if self.manifest_profile == "correction_sweep"
                 else READER_CAPABILITIES)
        return _version_key(compatibility["min_reader"]) <= version <= _version_key(
            compatibility["max_reader"]
        ) and set(compatibility["required_capabilities"]) <= (
            prior | READER_CAPABILITIES_V3 | READER_CAPABILITIES_V4 | READER_CAPABILITIES_V5
            | READER_CAPABILITIES_V6 | READER_CAPABILITIES_V7 | READER_CAPABILITIES_V8
            | READER_CAPABILITIES_V9 | set(available_capabilities)
        )

    def section(self, name: str) -> dict[str, Any]:
        paths = section_paths_v9(self.manifest_profile)
        if name not in paths:
            raise ContractError(f"unknown policy section {name!r}")
        return _section(self.payload, paths[name])


def canonical_manifest_bytes_v9(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v9(payload)
    for key, expected in {
        "product_instance_id": product_id,
        "portfolio_phase_revision_id": phase_revision_id,
    }.items():
        if expected is not None and normalized[key] != str(expected).lower():
            _fail(f"manifest.{key}", "differs from the revision row",
                  ManifestReason.IDENTITY_MISMATCH)
    if manifest_version is not None and normalized["manifest_version"] != manifest_version:
        _fail("manifest.manifest_version", "differs from the revision row",
              ManifestReason.IDENTITY_MISMATCH)
    return _serialize(normalized)


def load_canonical_manifest_v9(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV9:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v9(
        payload, product_id=product_id, phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV9(
        payload=freeze_json(normalized), canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(_serialize(normalized["service_principal_grants"])).hexdigest(),
    )


def policy_leaf_paths_v9(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v8(payload)
