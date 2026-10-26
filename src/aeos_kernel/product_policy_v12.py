"""Closed serving-surface declarations composed with immutable v11 product policy."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Mapping
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.product_policy import (
    ManifestReason,
    _fail,
    _object,
    _reference,
    _serialize,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v3 import _product_security
from aeos_kernel.product_policy_v10 import _serialize_v10
from aeos_kernel.product_policy_v11 import (
    SCHEMA_VERSION_V11,
    CanonicalProductManifestV11,
    normalize_manifest_payload_v11,
    policy_leaf_paths_v11,
    purpose_principal_classes_v11,
    section_authority_classes_v11,
    section_paths_v11,
)
from aeos_kernel.runtime_policy import ProductSecurity

SCHEMA_VERSION_V12: Final = "aeos.product-manifest.v12"
READER_VERSION_V12: Final = "12.0.0"
READER_CAPABILITIES_V12: Final = frozenset({SCHEMA_VERSION_V12, "canonical_manifest_bytes_v12"})
#: Exactly one declaration per surface, serialized in this order.
SERVING_SURFACE_KEYS_V12: Final = ("public_website", "application_api", "operator_desk")
# Mirrors the schema pattern: a host, a path and nothing that carries credentials or state.
_HTTPS_ENDPOINT: Final = re.compile(r"https://[^\s/?#@]+/[^\s?#]*")


def section_authority_classes_v12(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v11(profile)


def section_paths_v12(profile: str) -> Mapping[str, tuple[str, ...]]:
    # The existing product_security section owns the complete security object.
    return section_paths_v11(profile)


def purpose_principal_classes_v12(profile: str) -> Mapping[str, str]:
    return purpose_principal_classes_v11(profile)


def _surface(value: Any, path: str) -> str:
    if not isinstance(value, str) or value not in SERVING_SURFACE_KEYS_V12:
        _fail(path, "must be public_website, application_api or operator_desk")
    return cast(str, value)


def _public(value: Any, path: str) -> str:
    if value != "public":
        _fail(path, 'must be "public"')
    return "public"


def _https_endpoint(value: Any, path: str) -> str:
    text = _reference(value, path)
    if _HTTPS_ENDPOINT.fullmatch(text) is None:
        _fail(path, "must be an absolute HTTPS URL without credentials, query or fragment")
    return text


def _uptime_percent(value: Any, path: str) -> Decimal:
    # Strict-decoder tokens arrive as Decimal; float mappings keep their JSON spelling.
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        _fail(path, "must be a finite JSON number greater than 0 and at most 100")
    number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    if not number.is_finite() or number <= 0 or number > 100:
        _fail(path, "must be a finite JSON number greater than 0 and at most 100")
    return number


def _literal(expected: int) -> Any:
    def validate(value: Any, path: str) -> int:
        if type(value) is not int or value != expected:
            _fail(path, f"must be the JSON integer {expected}")
        return cast(int, value)

    return validate


def _uptime_window(value: Any, path: str) -> int:
    if type(value) is not int or value <= 0 or value % 300:
        _fail(path, "must be a positive JSON integer multiple of 300")
    return cast(int, value)


_DECLARATION = _object(
    {
        "surface_key": _surface,
        "surface_type": _surface,
        "endpoint_ref": _https_endpoint,
        "auth_posture": _public,
        "uptime_target_pct": _uptime_percent,
        "p95_latency_target_ms": _literal(500),
        "uptime_window_seconds": _uptime_window,
        "p95_window_seconds": _literal(300),
        "p95_breach_windows": _literal(3),
        "probe_interval_seconds": _literal(300),
        "runtime_ref": _reference,
        "decision_ref": _reference,
    }
)


def _serving_surfaces(value: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(SERVING_SURFACE_KEYS_V12):
        _fail(path, "must hold exactly one declaration for each serving surface")
    declared: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(cast(list[Any], value)):
        item = _DECLARATION(entry, f"{path}[{index}]")
        if item["surface_type"] != item["surface_key"]:
            _fail(f"{path}[{index}].surface_type", "must equal surface_key")
        if item["surface_key"] in declared:
            _fail(f"{path}[{index}].surface_key", "repeats an earlier declaration")
        declared[item["surface_key"]] = item
    return [declared[key] for key in SERVING_SURFACE_KEYS_V12]


def normalize_manifest_payload_v12(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V12:
        _fail("manifest.schema_version", "is not a v12 schema", ManifestReason.INCOMPATIBLE)
    security = payload.get("security")
    if not isinstance(security, Mapping):
        _fail("manifest.security", "must be an object")
    security = cast(Mapping[str, Any], security)
    surfaces = _serving_surfaces(
        security.get("serving_surfaces"), "manifest.security.serving_surfaces"
    )
    # Validate all inherited fields through v11 without rewriting historical bytes.
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V11
    prior["security"] = {key: item for key, item in security.items() if key != "serving_surfaces"}
    normalized = normalize_manifest_payload_v11(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V12:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v12 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V12
    normalized["security"]["serving_surfaces"] = surfaces
    return normalized


class CanonicalProductManifestV12(CanonicalProductManifestV11):
    """V11 policy with the three closed public serving-surface declarations."""

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V12,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        return super().reader_compatible(
            reader_version,
            available_capabilities=READER_CAPABILITIES_V12 | set(available_capabilities),
        )

    def product_security(self, product_slug: str) -> ProductSecurity:
        security = dict(self.payload["security"])
        security.pop("serving_surfaces")
        security.pop("alert_sla")
        targets = security.pop("slo_targets")
        security["audit_retention_days"] = targets["audit_retention_days"]
        return _product_security(
            security, product_slug=product_slug, manifest_digest=self.manifest_digest
        )


def canonical_manifest_bytes_v12(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v12(payload)
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


def load_canonical_manifest_v12(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV12:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v12(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = decode_strict_json(canonical)
    return CanonicalProductManifestV12(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths_v12(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v11(payload)
