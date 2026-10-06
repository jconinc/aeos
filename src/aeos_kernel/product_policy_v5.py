"""PB-224 source binding composed with the immutable v4 manifest contract.

The host authenticates the complete measurement policy and its adoption. This parser only
binds its version and digest; explicit null means no adopted policy, never default values.
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
    _at,
    _fail,
    _object,
    _reference,
    _serialize,
    _sha256,
    _version_key,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v2 import READER_CAPABILITIES_V2
from aeos_kernel.product_policy_v3 import READER_CAPABILITIES_V3
from aeos_kernel.product_policy_v4 import (
    READER_CAPABILITIES_V4,
    SCHEMA_VERSION_V4,
    CanonicalProductManifestV4,
    normalize_manifest_payload_v4,
    policy_leaf_paths_v4,
    purpose_principal_classes_v4,
    section_authority_classes_v4,
    section_paths_v4,
)

SCHEMA_VERSION_V5: Final = "aeos.product-manifest.v5"
READER_VERSION_V5: Final = "5.0.0"
READER_CAPABILITIES_V5: Final = frozenset(
    {SCHEMA_VERSION_V5, "canonical_manifest_bytes_v5", "support_measure_policy_binding_v1"}
)
REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5: Final = frozenset(
    {"support_measure_policy_source_v1"}
)
_BINDING = _object({"version": _reference, "digest": _sha256})


def section_authority_classes_v5(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v4(profile)


def section_paths_v5(profile: str) -> Mapping[str, tuple[str, ...]]:
    return section_paths_v4(profile)


def purpose_principal_classes_v5(profile: str) -> Mapping[str, str]:
    return purpose_principal_classes_v4(profile)


def normalize_manifest_payload_v5(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V5:
        _fail("manifest.schema_version", "is not a v5 schema", ManifestReason.INCOMPATIBLE)
    bindings = payload.get("source_bindings")
    if not isinstance(bindings, Mapping) or "support_measure_policy" not in bindings:
        _fail("manifest.source_bindings.support_measure_policy", "must be explicit")
    bindings = cast(Mapping[str, Any], bindings)
    binding = bindings["support_measure_policy"]
    if binding is not None:
        binding = _BINDING(binding, "manifest.source_bindings.support_measure_policy")
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V4
    prior["source_bindings"] = {
        key: value for key, value in bindings.items() if key != "support_measure_policy"
    }
    normalized = normalize_manifest_payload_v4(prior)
    required = READER_CAPABILITIES_V5 | (
        REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5 if binding is not None else frozenset()
    )
    if not set(normalized["compatibility"]["required_capabilities"]) >= required:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v5 and bound-source capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V5
    normalized["source_bindings"]["support_measure_policy"] = binding
    return normalized


class CanonicalProductManifestV5(CanonicalProductManifestV4):
    """V5 retains the exact profile, grants, thresholds and security of v4."""

    @property
    def support_measure_policy_binding(self) -> Mapping[str, str] | None:
        return cast(
            Mapping[str, str] | None, self.payload["source_bindings"]["support_measure_policy"]
        )

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V5,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        compatibility = self.payload["compatibility"]
        version = _version_key(reader_version)
        prior = (
            READER_CAPABILITIES_V2
            if self.manifest_profile == "correction_sweep"
            else READER_CAPABILITIES
        )
        return _version_key(compatibility["min_reader"]) <= version <= _version_key(
            compatibility["max_reader"]
        ) and set(compatibility["required_capabilities"]) <= (
            prior | READER_CAPABILITIES_V3 | READER_CAPABILITIES_V4 | READER_CAPABILITIES_V5
            | set(available_capabilities)
        )

    def section(self, name: str) -> dict[str, Any]:
        paths = section_paths_v5(self.manifest_profile)
        if name not in paths:
            raise ContractError(f"unknown policy section {name!r}")
        return {path: _at(self.payload, path) for path in paths[name]}


def canonical_manifest_bytes_v5(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v5(payload)
    for key, expected in {
        "product_instance_id": product_id,
        "portfolio_phase_revision_id": phase_revision_id,
    }.items():
        if expected is not None and normalized[key] != str(expected).lower():
            _fail(
                f"manifest.{key}", "differs from the revision row", ManifestReason.IDENTITY_MISMATCH
            )
    if manifest_version is not None and normalized["manifest_version"] != manifest_version:
        _fail("manifest.manifest_version", "differs from the revision row",
              ManifestReason.IDENTITY_MISMATCH)
    return _serialize(normalized)


def load_canonical_manifest_v5(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV5:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v5(
        payload, product_id=product_id, phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV5(
        payload=freeze_json(normalized), canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(_serialize(normalized["service_principal_grants"])).hexdigest(),
    )


def policy_leaf_paths_v5(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v4(payload)
