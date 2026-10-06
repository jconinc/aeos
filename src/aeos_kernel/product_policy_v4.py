"""PB-211 commercial thresholds composed with the v3 security/profile contract.

Historical readers remain unchanged. Values and precise principal grants are owner policy;
this parser grants neither source authority, payback canon approval nor spending permission.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, cast
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.product_policy import (
    PURPOSE_PRINCIPAL_CLASSES,
    READ_ONLY_PURPOSES,
    READER_CAPABILITIES,
    ManifestReason,
    _enum,
    _fail,
    _identifier,
    _object,
    _principal_id,
    _serialize,
    _set_of,
    _version_key,
    canonical_decimal,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v2 import (
    PURPOSE_PRINCIPAL_CLASSES_V2,
    READER_CAPABILITIES_V2,
)
from aeos_kernel.product_policy_v3 import (
    READER_CAPABILITIES_V3,
    SCHEMA_VERSION_V3,
    CanonicalProductManifestV3,
    normalize_manifest_payload_v3,
    policy_leaf_paths_v3,
    section_authority_classes_v3,
    section_paths_v3,
)

SCHEMA_VERSION_V4: Final = "aeos.product-manifest.v4"
READER_VERSION_V4: Final = "4.0.0"
COMMERCIAL_THRESHOLDS_CAPABILITY: Final = "commercial_thresholds_v1"
READER_CAPABILITIES_V4: Final = frozenset(
    {SCHEMA_VERSION_V4, "canonical_manifest_bytes_v4", COMMERCIAL_THRESHOLDS_CAPABILITY}
)
COMMERCIAL_PURPOSE_PRINCIPAL_CLASSES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "commercial_scale_admission": "commercial_scale_admission_service",
        "commercial_paid_effect": "commercial_paid_effect_worker",
    }
)
READ_ONLY_PURPOSES_V4: Final = READ_ONLY_PURPOSES | {"commercial_scale_admission"}


def purpose_principal_classes_v4(profile: str) -> Mapping[str, str]:
    _enum({"base", "correction_sweep"})(profile, "manifest.manifest_profile")
    prior = (
        PURPOSE_PRINCIPAL_CLASSES_V2
        if profile == "correction_sweep"
        else (PURPOSE_PRINCIPAL_CLASSES)
    )
    return MappingProxyType({**prior, **COMMERCIAL_PURPOSE_PRINCIPAL_CLASSES})


def section_authority_classes_v4(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v3(profile)


def section_paths_v4(profile: str) -> Mapping[str, tuple[str, ...]]:
    prior = section_paths_v3(profile)
    return MappingProxyType(
        {**prior, "commercial_terms": (*prior["commercial_terms"], "commercial.cac_ltv_thresholds")}
    )


def _threshold(value: Any, path: str, *, positive: bool) -> str:
    result = canonical_decimal(value, path)
    if Decimal(result) < 0 or (positive and Decimal(result) == 0):
        _fail(path, "must be positive" if positive else "must be nonnegative")
    return result


def _positive_threshold(value: Any, path: str) -> str:
    return _threshold(value, path, positive=True)


def _nonnegative_threshold(value: Any, path: str) -> str:
    return _threshold(value, path, positive=False)


_THRESHOLDS = _object(
    {
        "max_cac_usd": _nonnegative_threshold,
        "min_ltv_cac_ratio": _positive_threshold,
        "payback_months_max": _positive_threshold,
    }
)


def normalize_manifest_payload_v4(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V4:
        _fail("manifest.schema_version", "is not a v4 schema", ManifestReason.INCOMPATIBLE)
    profile = _enum({"base", "correction_sweep"})(
        payload.get("manifest_profile"), "manifest.manifest_profile"
    )
    commercial = payload.get("commercial")
    if not isinstance(commercial, Mapping):
        _fail("manifest.commercial", "must be an object")
    commercial = cast(Mapping[str, Any], commercial)
    thresholds = _THRESHOLDS(
        commercial.get("cac_ltv_thresholds"), "manifest.commercial.cac_ltv_thresholds"
    )
    classes = purpose_principal_classes_v4(profile)

    def grant(value: Any, path: str) -> dict[str, Any]:
        row = _object(
            {"purpose": _identifier, "principal_id": _principal_id, "principal_class": _identifier}
        )(value, path)
        expected = classes.get(row["purpose"])
        if expected is None or row["principal_class"] != expected:
            _fail(
                path, "does not match the registered purpose/class", ManifestReason.GRANT_MISMATCH
            )
        return dict(row)

    grants = _set_of(grant)(
        payload.get("service_principal_grants"), "manifest.service_principal_grants"
    )
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V3
    prior["commercial"] = {
        key: value for key, value in commercial.items() if key != "cac_ltv_thresholds"
    }
    prior["service_principal_grants"] = [
        row for row in grants if row["purpose"] not in COMMERCIAL_PURPOSE_PRINCIPAL_CLASSES
    ]
    normalized = normalize_manifest_payload_v3(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V4:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v4 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V4
    normalized["commercial"]["cac_ltv_thresholds"] = thresholds
    normalized["service_principal_grants"] = grants
    return normalized


class CanonicalProductManifestV4(CanonicalProductManifestV3):
    """Immutable v4 policy retains v3 security and the exact selected sweep/base profile."""

    @property
    def cac_ltv_thresholds(self) -> Mapping[str, str]:
        return cast(Mapping[str, str], self.payload["commercial"]["cac_ltv_thresholds"])

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V4,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        compatibility = self.payload["compatibility"]
        version = _version_key(reader_version)
        prior = (
            READER_CAPABILITIES_V2
            if self.manifest_profile == "correction_sweep"
            else (READER_CAPABILITIES)
        )
        return _version_key(compatibility["min_reader"]) <= version <= _version_key(
            compatibility["max_reader"]
        ) and set(compatibility["required_capabilities"]) <= (
            prior | READER_CAPABILITIES_V3 | READER_CAPABILITIES_V4 | set(available_capabilities)
        )

    def section(self, name: str) -> dict[str, Any]:
        from aeos_kernel.errors import ContractError
        from aeos_kernel.product_policy import _at

        paths = section_paths_v4(self.manifest_profile)
        if name not in paths:
            raise ContractError(f"unknown policy section {name!r}")
        return {path: _at(self.payload, path) for path in paths[name]}


def canonical_manifest_bytes_v4(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v4(payload)
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


def load_canonical_manifest_v4(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV4:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v4(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV4(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths_v4(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v3(payload)
