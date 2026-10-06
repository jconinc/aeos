"""PB-219/PB-226 WLG service grants composed with the immutable v5 manifest contract.

Native capture and operation each require an explicit purpose and service class. The parser
grants no host, source-owner, native-project or execution authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    READER_CAPABILITIES,
    ManifestReason,
    _at,
    _fail,
    _identifier,
    _object,
    _principal_id,
    _serialize,
    _set_of,
    _version_key,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v2 import READER_CAPABILITIES_V2
from aeos_kernel.product_policy_v3 import READER_CAPABILITIES_V3
from aeos_kernel.product_policy_v4 import READER_CAPABILITIES_V4
from aeos_kernel.product_policy_v5 import (
    READER_CAPABILITIES_V5,
    SCHEMA_VERSION_V5,
    CanonicalProductManifestV5,
    normalize_manifest_payload_v5,
    policy_leaf_paths_v5,
    purpose_principal_classes_v5,
    section_authority_classes_v5,
    section_paths_v5,
)

SCHEMA_VERSION_V6: Final = "aeos.product-manifest.v6"
READER_VERSION_V6: Final = "6.0.0"
READER_CAPABILITIES_V6: Final = frozenset(
    {SCHEMA_VERSION_V6, "canonical_manifest_bytes_v6", "wlg_service_principal_grants_v1"}
)
REQUIRED_WLG_HOST_CAPABILITIES_V6: Final = frozenset({"wlg_native_source_admission_v1"})
WLG_PURPOSE_PRINCIPAL_CLASSES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "wlg_capture_admission": "wlg_capture_service",
        "wlg_operation_admission": "wlg_operation_service",
    }
)


def section_authority_classes_v6(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v5(profile)


def section_paths_v6(profile: str) -> Mapping[str, tuple[str, ...]]:
    return section_paths_v5(profile)


def purpose_principal_classes_v6(profile: str) -> Mapping[str, str]:
    return MappingProxyType(
        {**purpose_principal_classes_v5(profile), **WLG_PURPOSE_PRINCIPAL_CLASSES}
    )


def normalize_manifest_payload_v6(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V6:
        _fail("manifest.schema_version", "is not a v6 schema", ManifestReason.INCOMPATIBLE)
    classes = purpose_principal_classes_v6(str(payload.get("manifest_profile", "")))

    def grant(value: Any, path: str) -> dict[str, Any]:
        row = _object(
            {
                "purpose": _identifier,
                "principal_id": _principal_id,
                "principal_class": _identifier,
            }
        )(value, path)
        if classes.get(row["purpose"]) != row["principal_class"]:
            _fail(
                path, "does not match the registered purpose/class", ManifestReason.GRANT_MISMATCH
            )
        return dict(row)

    grants = _set_of(grant)(
        payload.get("service_principal_grants"), "manifest.service_principal_grants"
    )
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V5
    prior["service_principal_grants"] = [
        row for row in grants if row["purpose"] not in WLG_PURPOSE_PRINCIPAL_CLASSES
    ]
    normalized = normalize_manifest_payload_v5(prior)
    required = READER_CAPABILITIES_V6 | (
        REQUIRED_WLG_HOST_CAPABILITIES_V6
        if any(row["purpose"] in WLG_PURPOSE_PRINCIPAL_CLASSES for row in grants)
        else frozenset()
    )
    if not set(normalized["compatibility"]["required_capabilities"]) >= required:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v6 and WLG host capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V6
    normalized["service_principal_grants"] = grants
    return normalized


class CanonicalProductManifestV6(CanonicalProductManifestV5):
    """V6 retains v5 policy and adds two distinct, explicit WLG service grants."""

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V6,
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
            prior
            | READER_CAPABILITIES_V3
            | READER_CAPABILITIES_V4
            | READER_CAPABILITIES_V5
            | READER_CAPABILITIES_V6
            | set(available_capabilities)
        )

    def section(self, name: str) -> dict[str, Any]:
        paths = section_paths_v6(self.manifest_profile)
        if name not in paths:
            raise ContractError(f"unknown policy section {name!r}")
        return {path: _at(self.payload, path) for path in paths[name]}


def canonical_manifest_bytes_v6(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v6(payload)
    for key, expected in {
        "product_instance_id": product_id,
        "portfolio_phase_revision_id": phase_revision_id,
    }.items():
        if expected is not None and normalized[key] != str(expected).lower():
            _fail(
                f"manifest.{key}", "differs from the revision row", ManifestReason.IDENTITY_MISMATCH
            )
    if manifest_version is not None and normalized["manifest_version"] != manifest_version:
        _fail(
            "manifest.manifest_version",
            "differs from the revision row",
            ManifestReason.IDENTITY_MISMATCH,
        )
    return _serialize(normalized)


def load_canonical_manifest_v6(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV6:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v6(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV6(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths_v6(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v5(payload)
