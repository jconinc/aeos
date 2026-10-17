"""Closed alert targets composed with immutable v10 product policy."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.product_policy import (
    ManifestReason,
    _fail,
    _object,
    _serialize,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v3 import _product_security
from aeos_kernel.product_policy_v10 import (
    SCHEMA_VERSION_V10,
    CanonicalProductManifestV10,
    _serialize_v10,
    normalize_manifest_payload_v10,
    policy_leaf_paths_v10,
    purpose_principal_classes_v10,
    section_authority_classes_v10,
    section_paths_v10,
)
from aeos_kernel.runtime_policy import ProductSecurity

SCHEMA_VERSION_V11: Final = "aeos.product-manifest.v11"
READER_VERSION_V11: Final = "11.0.0"
READER_CAPABILITIES_V11: Final = frozenset({SCHEMA_VERSION_V11, "canonical_manifest_bytes_v11"})


def section_authority_classes_v11(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v10(profile)


def section_paths_v11(profile: str) -> Mapping[str, tuple[str, ...]]:
    # The existing product_security section owns the complete security object.
    return section_paths_v10(profile)


def purpose_principal_classes_v11(profile: str) -> Mapping[str, str]:
    return purpose_principal_classes_v10(profile)


def _positive_number(value: Any, path: str) -> Decimal:
    # Decimal preserves strict-decoder tokens exactly, without binary-float bounds.
    # Mapping floats use their JSON spelling; inherited integer fields stay strict.
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        _fail(path, "must be a positive finite JSON number measured in seconds")
    number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    if not number.is_finite() or number <= 0:
        _fail(path, "must be a positive finite JSON number measured in seconds")
    return number


def _window(value: Any, path: str) -> int:
    if type(value) is not int or value != 1440:
        _fail(path, "must be the JSON integer 1440")
    return cast(int, value)


_ALERT_SLA = _object(
    {
        "window_minutes": _window,
        "seconds_by_severity": _object(
            {severity: _positive_number for severity in ("critical", "high", "moderate", "low")}
        ),
    }
)


def normalize_manifest_payload_v11(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V11:
        _fail("manifest.schema_version", "is not a v11 schema", ManifestReason.INCOMPATIBLE)
    security = payload.get("security")
    if not isinstance(security, Mapping):
        _fail("manifest.security", "must be an object")
    security = cast(Mapping[str, Any], security)
    alert_sla = _ALERT_SLA(security.get("alert_sla"), "manifest.security.alert_sla")
    # Validate all inherited fields through v10 without rewriting historical bytes.
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V10
    prior["security"] = {key: item for key, item in security.items() if key != "alert_sla"}
    normalized = normalize_manifest_payload_v10(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V11:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v11 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V11
    normalized["security"]["alert_sla"] = alert_sla
    return normalized


class CanonicalProductManifestV11(CanonicalProductManifestV10):
    """V10 policy with closed per-severity alert targets."""

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V11,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        return super().reader_compatible(
            reader_version,
            available_capabilities=READER_CAPABILITIES_V11 | set(available_capabilities),
        )

    def product_security(self, product_slug: str) -> ProductSecurity:
        security = dict(self.payload["security"])
        security.pop("alert_sla")
        targets = security.pop("slo_targets")
        security["audit_retention_days"] = targets["audit_retention_days"]
        return _product_security(
            security, product_slug=product_slug, manifest_digest=self.manifest_digest
        )


def canonical_manifest_bytes_v11(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v11(payload)
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
    return _serialize_v10(normalized)


def load_canonical_manifest_v11(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV11:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v11(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = decode_strict_json(canonical)
    return CanonicalProductManifestV11(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths_v11(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v10(payload)
