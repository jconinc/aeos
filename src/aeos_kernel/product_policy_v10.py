"""Explicit operational objectives composed with the immutable v9 manifest.

The closed SLO block owns retention's only v10 location. Its operational reader grant
reads policy; it approves no manifest, measurement, breach response or external effect.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, cast
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.product_policy import (
    ManifestReason,
    _fail,
    _identifier,
    _nonnegative,
    _object,
    _positive,
    _principal_id,
    _serialize,
    _set_of,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v3 import _product_security
from aeos_kernel.product_policy_v9 import (
    SCHEMA_VERSION_V9,
    CanonicalProductManifestV9,
    normalize_manifest_payload_v9,
    policy_leaf_paths_v9,
    purpose_principal_classes_v9,
    section_authority_classes_v9,
    section_paths_v9,
)
from aeos_kernel.runtime_policy import ProductSecurity

SCHEMA_VERSION_V10: Final = "aeos.product-manifest.v10"
READER_VERSION_V10: Final = "10.0.0"
READER_CAPABILITIES_V10: Final = frozenset({SCHEMA_VERSION_V10, "canonical_manifest_bytes_v10"})


def section_authority_classes_v10(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v9(profile)


def section_paths_v10(profile: str) -> Mapping[str, tuple[str, ...]]:
    # The existing product_security section owns the complete security object.
    return section_paths_v9(profile)


def purpose_principal_classes_v10(profile: str) -> Mapping[str, str]:
    return MappingProxyType(
        {
            **purpose_principal_classes_v9(profile),
            "operational_objectives": "operational_objectives_reader",
        }
    )


def _positive_number(value: Any, path: str) -> Decimal:
    # Decimal preserves strict-decoder tokens exactly, without binary-float bounds.
    # Mapping floats use their JSON spelling; inherited integer fields stay strict.
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        _fail(path, "must be a positive finite JSON number measured in minutes")
    number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    if not number.is_finite() or number <= 0:
        _fail(path, "must be a positive finite JSON number measured in minutes")
    return number


def _serialize_v10(value: Any) -> bytes:
    """Serialize validated v10 JSON, retaining exact decimal numbers locally."""

    if isinstance(value, Decimal):
        parts = value.as_tuple()
        digits = list(parts.digits)
        exponent = cast(int, parts.exponent)
        # Unlike Decimal.normalize(), tuple construction never rounds to the active
        # decimal context. Equivalent integer/fraction/exponent forms share bytes.
        while digits[-1] == 0:
            digits.pop()
            exponent += 1
        token = str(Decimal((parts.sign, tuple(digits), exponent)))
        return token.lower().replace("e+", "e").encode("ascii")
    if isinstance(value, Mapping):
        return (
            b"{"
            + b",".join(
                _serialize(key) + b":" + _serialize_v10(value[key]) for key in sorted(value)
            )
            + b"}"
        )
    if isinstance(value, list):
        return b"[" + b",".join(_serialize_v10(item) for item in value) + b"]"
    return _serialize(value)


_SLO_TARGETS = _object(
    {
        "rpo_minutes": _nonnegative,
        "rto_minutes": _nonnegative,
        "audit_retention_days": _positive,
        "delivery_receipt_sla_minutes": _positive_number,
    }
)


def normalize_manifest_payload_v10(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V10:
        _fail("manifest.schema_version", "is not a v10 schema", ManifestReason.INCOMPATIBLE)
    security = payload.get("security")
    if not isinstance(security, Mapping):
        _fail("manifest.security", "must be an object")
    security = cast(Mapping[str, Any], security)
    if "audit_retention_days" in security:
        _fail("manifest.security.audit_retention_days", "belongs only in slo_targets in v10")
    targets = _SLO_TARGETS(security.get("slo_targets"), "manifest.security.slo_targets")
    classes = purpose_principal_classes_v10(str(payload.get("manifest_profile", "")))

    def grant(value: Any, path: str) -> dict[str, Any]:
        row = _object(
            {"purpose": _identifier, "principal_id": _principal_id, "principal_class": _identifier}
        )(value, path)
        if classes.get(row["purpose"]) != row["principal_class"]:
            _fail(
                path, "does not match the registered purpose/class", ManifestReason.GRANT_MISMATCH
            )
        return dict(row)

    grants = _set_of(grant)(
        payload.get("service_principal_grants"), "manifest.service_principal_grants"
    )
    # v9 validates every inherited field through an in-memory prior view. Never
    # serialize that view as v10: the output restores the sole canonical SLO block.
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V9
    prior["security"] = {
        **{key: item for key, item in security.items() if key != "slo_targets"},
        "audit_retention_days": targets["audit_retention_days"],
    }
    prior["service_principal_grants"] = [
        row for row in grants if row["purpose"] != "operational_objectives"
    ]
    normalized = normalize_manifest_payload_v9(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V10:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v10 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V10
    del normalized["security"]["audit_retention_days"]
    normalized["security"]["slo_targets"] = targets
    normalized["service_principal_grants"] = grants
    return normalized


class CanonicalProductManifestV10(CanonicalProductManifestV9):
    """V9 policy with explicitly approved operational objectives and read-only access."""

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V10,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        return super().reader_compatible(
            reader_version,
            available_capabilities=READER_CAPABILITIES_V10 | set(available_capabilities),
        )

    def product_security(self, product_slug: str) -> ProductSecurity:
        security = dict(self.payload["security"])
        targets = security.pop("slo_targets")
        security["audit_retention_days"] = targets["audit_retention_days"]
        return _product_security(
            security, product_slug=product_slug, manifest_digest=self.manifest_digest
        )


def canonical_manifest_bytes_v10(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v10(payload)
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


def load_canonical_manifest_v10(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV10:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v10(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = decode_strict_json(canonical)
    return CanonicalProductManifestV10(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths_v10(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v9(payload)
