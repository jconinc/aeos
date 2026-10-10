"""Answer-engine probe spending limits and Authority signal methods in manifest v8.

The v8 contract composes the immutable v7 manifest with two adopted records:

* five spending keys in the existing ``authority.probe_budget`` object (``budget`` section):
  each is required and nullable, null means not approved, and no value is ever supplied;
* ``authority.brand_search_methodology`` and ``authority.platform_set`` in the existing
  ``authority_targets`` section.

Parsing never approves a value, chooses a provider or grants spending authority. The host
admits a model call only against an active, approved manifest and its own gateway ceilings.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from types import MappingProxyType
from typing import Any, Final, cast
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    READER_CAPABILITIES,
    ManifestReason,
    _fail,
    _identifier,
    _object,
    _positive,
    _section,
    _serialize,
    _set_of,
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
from aeos_kernel.product_policy_v7 import (
    READER_CAPABILITIES_V7,
    SCHEMA_VERSION_V7,
    CanonicalProductManifestV7,
    normalize_manifest_payload_v7,
    policy_leaf_paths_v7,
    purpose_principal_classes_v7,
    section_authority_classes_v7,
    section_paths_v7,
)

SCHEMA_VERSION_V8: Final = "aeos.product-manifest.v8"
READER_VERSION_V8: Final = "8.0.0"
READER_CAPABILITIES_V8: Final = frozenset(
    {
        SCHEMA_VERSION_V8,
        "canonical_manifest_bytes_v8",
        "authority_probe_spending_v1",
        "authority_signal_methods_v1",
    }
)
#: The probe spending keys, in the order the record defines them. Money is in minor units.
PROBE_SPENDING_KEYS: Final = (
    "window_days",
    "per_call_ceiling_minor",
    "window_ceiling_minor",
    "daily_ceiling_minor",
    "monthly_ceiling_minor",
)
AUTHORITY_SIGNAL_KEYS: Final = ("brand_search_methodology", "platform_set")


def section_authority_classes_v8(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v7(profile)


def section_paths_v8(profile: str) -> Mapping[str, tuple[str, ...]]:
    prior = section_paths_v7(profile)
    return MappingProxyType({
        **prior,
        "authority_targets": (
            *prior["authority_targets"],
            "authority.brand_search_methodology",
            "authority.platform_set",
        ),
    })


def purpose_principal_classes_v8(profile: str) -> Mapping[str, str]:
    return purpose_principal_classes_v7(profile)


def _positive_minor(value: Any, path: str) -> str:
    text = canonical_integer_string(value, path, signed=False)
    if text == "0":
        _fail(path, "must be a positive amount in minor units")
    return text


_PROBE_SPENDING = _object(
    {
        "window_days": _positive,
        "per_call_ceiling_minor": _positive_minor,
        "window_ceiling_minor": _positive_minor,
        "daily_ceiling_minor": _positive_minor,
        "monthly_ceiling_minor": _positive_minor,
    },
    nullable=frozenset(PROBE_SPENDING_KEYS),
)
_PLATFORM_SET = _object({"id": _identifier, "platform_keys": _set_of(_identifier, nonempty=True)})


def normalize_probe_spending_v1(
    value: Mapping[str, Any], path: str = "manifest.authority.probe_budget"
) -> dict[str, Any]:
    """All five keys null (not approved) or all set, with ordered ceilings; nothing defaults."""

    row = _PROBE_SPENDING(value, path)
    unset = [key for key in PROBE_SPENDING_KEYS if row[key] is None]
    if unset and len(unset) != len(PROBE_SPENDING_KEYS):
        _fail(f"{path}.{unset[0]}", "is null while other spending limits are set")
    if not unset:
        per_call, window, daily, monthly = (
            int(row[key]) for key in PROBE_SPENDING_KEYS[1:]
        )
        if per_call > window:
            _fail(f"{path}.per_call_ceiling_minor", "exceeds window_ceiling_minor")
        if per_call > daily:
            _fail(f"{path}.per_call_ceiling_minor", "exceeds daily_ceiling_minor")
        if daily > monthly:
            _fail(f"{path}.daily_ceiling_minor", "exceeds monthly_ceiling_minor")
    return dict(row)


def normalize_authority_signals_v1(
    value: Mapping[str, Any], path: str = "manifest.authority"
) -> dict[str, Any]:
    """Each method is named exactly, or null while not approved; the host checks the name."""

    return dict(
        _object(
            {"brand_search_methodology": _identifier, "platform_set": _PLATFORM_SET},
            nullable=frozenset(AUTHORITY_SIGNAL_KEYS),
        )(value, path)
    )


def normalize_manifest_payload_v8(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V8:
        _fail("manifest.schema_version", "is not a v8 schema", ManifestReason.INCOMPATIBLE)
    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        _fail("manifest.authority", "must be an object")
    authority = cast(Mapping[str, Any], authority)
    budget = authority.get("probe_budget")
    if not isinstance(budget, Mapping):
        _fail("manifest.authority.probe_budget", "must be an object")
    budget = cast(Mapping[str, Any], budget)
    spending = normalize_probe_spending_v1(
        {key: item for key, item in budget.items() if key in PROBE_SPENDING_KEYS}
    )
    signals = normalize_authority_signals_v1(
        {key: item for key, item in authority.items() if key in AUTHORITY_SIGNAL_KEYS}
    )
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V7
    prior["authority"] = {
        key: item for key, item in authority.items() if key not in AUTHORITY_SIGNAL_KEYS
    }
    prior["authority"]["probe_budget"] = {
        key: item for key, item in budget.items() if key not in PROBE_SPENDING_KEYS
    }
    normalized = normalize_manifest_payload_v7(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V8:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v8 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V8
    normalized["authority"]["probe_budget"].update(spending)
    normalized["authority"].update(signals)
    return normalized


class CanonicalProductManifestV8(CanonicalProductManifestV7):
    """V8 adds probe spending limits to the budget section and signal methods to targets."""

    @property
    def probe_spending(self) -> dict[str, Any]:
        """The five limits as an independent object; all None while not approved."""

        budget = self.payload["authority"]["probe_budget"]
        return normalize_probe_spending_v1({key: budget[key] for key in PROBE_SPENDING_KEYS})

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V8,
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
            | set(available_capabilities)
        )

    def section(self, name: str) -> dict[str, Any]:
        paths = section_paths_v8(self.manifest_profile)
        if name not in paths:
            raise ContractError(f"unknown policy section {name!r}")
        return _section(self.payload, paths[name])


def canonical_manifest_bytes_v8(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v8(payload)
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


def load_canonical_manifest_v8(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV8:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v8(
        payload, product_id=product_id, phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV8(
        payload=freeze_json(normalized), canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(_serialize(normalized["service_principal_grants"])).hexdigest(),
    )


def policy_leaf_paths_v8(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v7(payload)
