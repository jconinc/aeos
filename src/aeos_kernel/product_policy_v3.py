"""Versioned product security for the host's governed transport reader.

Security values are explicit owner policy, never defaults or inferred transport inventory.
Historical v1/v2 policy readers retain their original byte and approval contracts.
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
    SCHEMA_VERSION,
    SECTION_AUTHORITY_CLASSES,
    SECTION_PATHS,
    ManifestReason,
    _at,
    _boolean,
    _enum,
    _fail,
    _identifier,
    _object,
    _positive,
    _serialize,
    _set_of,
    _string,
    _version_key,
    decode_strict_json,
    manifest_digest,
    normalize_manifest_payload,
)
from aeos_kernel.product_policy_v2 import (
    READER_CAPABILITIES_V2,
    SCHEMA_VERSION_V2,
    SECTION_AUTHORITY_CLASSES_V2,
    SECTION_PATHS_V2,
    CanonicalProductManifestV2,
    normalize_manifest_payload_v2,
    policy_leaf_paths_v2,
)
from aeos_kernel.runtime_policy import HostTarget, ProductSecurity

SCHEMA_VERSION_V3: Final = "aeos.product-manifest.v3"
READER_VERSION_V3: Final = "3.0.0"
READER_CAPABILITIES_V3: Final = frozenset(
    {SCHEMA_VERSION_V3, "canonical_manifest_bytes_v3", "product_security_v3"}
)


def section_authority_classes_v3(profile: str) -> Mapping[str, str]:
    """The selected profile retains every approval section of its original contract."""
    _enum({"base", "correction_sweep"})(profile, "manifest.manifest_profile")
    previous = (
        SECTION_AUTHORITY_CLASSES_V2 if profile == "correction_sweep" else SECTION_AUTHORITY_CLASSES
    )
    return MappingProxyType({**previous, "product_security": "security_role"})


def section_paths_v3(profile: str) -> Mapping[str, tuple[str, ...]]:
    section_authority_classes_v3(profile)
    previous = SECTION_PATHS_V2 if profile == "correction_sweep" else SECTION_PATHS
    return MappingProxyType(
        {
            **previous,
            "product_scope": (*previous["product_scope"], "manifest_profile"),
            "product_security": ("security",),
        }
    )


def _host_target(value: Any, path: str) -> dict[str, Any]:
    fields = _object(
        {
            "scheme": _enum({"http", "https"}),
            "host": _string,
            "port": _positive,
            "purpose": _identifier,
        }
    )(value, path)
    try:
        HostTarget(**fields)
    except ContractError as error:
        _fail(path, str(error))
    return dict(fields)


def _selected_hosts(value: Any, path: str) -> list[dict[str, Any]] | None:
    # Explicit null inherits only the platform ceiling. An explicit empty array denies all.
    if value is None:
        return None
    return list(_set_of(_host_target)(value, path))


_SECURITY = _object(
    {
        "selected_hosts": _selected_hosts,
        "untrusted_sources": _set_of(_identifier),
        "go_live_mode": _enum({"staging", "live"}),
        "at_rest_required": _boolean,
        "in_transit_required": _boolean,
        "key_rotation_days": _positive,
        "audit_retention_days": _positive,
    }
)


def _product_security(
    value: Mapping[str, Any], *, product_slug: str, manifest_digest: str
) -> ProductSecurity:
    """Project a validated policy without changing any approved value."""
    fields = dict(value)
    hosts = fields.pop("selected_hosts")
    sources = fields.pop("untrusted_sources")
    return ProductSecurity(
        product_slug=product_slug,
        manifest_digest=manifest_digest,
        selected_hosts=None if hosts is None else tuple(HostTarget(**dict(row)) for row in hosts),
        untrusted_sources=tuple(sources),
        **fields,
    )


def normalize_manifest_payload_v3(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a closed base or sweep profile with explicitly approved security values."""
    if payload.get("schema_version") != SCHEMA_VERSION_V3:
        _fail("manifest.schema_version", "is not a v3 schema", ManifestReason.INCOMPATIBLE)
    profile = _enum({"base", "correction_sweep"})(
        payload.get("manifest_profile"), "manifest.manifest_profile"
    )
    security = _SECURITY(payload.get("security"), "manifest.security")
    # Validate the runtime projection too; identifiers and numeric bounds have one meaning.
    try:
        _product_security(security, product_slug="validation", manifest_digest="0" * 64)
    except ContractError as error:
        _fail("manifest.security", str(error))
    prior = dict(payload)
    del prior["manifest_profile"], prior["security"]
    prior["schema_version"] = SCHEMA_VERSION_V2 if profile == "correction_sweep" else SCHEMA_VERSION
    normalize = (
        normalize_manifest_payload_v2
        if profile == "correction_sweep"
        else normalize_manifest_payload
    )
    normalized = normalize(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V3:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v3 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized.update(schema_version=SCHEMA_VERSION_V3, manifest_profile=profile, security=security)
    return normalized


class CanonicalProductManifestV3(CanonicalProductManifestV2):
    """Immutable v3 policy; inherited fields retain their v1/v2 interpretation."""

    @property
    def manifest_profile(self) -> str:
        return str(self.payload["manifest_profile"])

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V3,
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
        ) and set(compatibility["required_capabilities"]) <= prior | READER_CAPABILITIES_V3 | set(
            available_capabilities
        )

    def section(self, name: str) -> dict[str, Any]:
        paths = section_paths_v3(self.manifest_profile)
        if name not in paths:
            raise ContractError(f"unknown policy section {name!r}")
        return {path: _at(self.payload, path) for path in paths[name]}

    def product_security(self, product_slug: str) -> ProductSecurity:
        return _product_security(
            self.payload["security"],
            product_slug=product_slug,
            manifest_digest=self.manifest_digest,
        )


def canonical_manifest_bytes_v3(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v3(payload)
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


def load_canonical_manifest_v3(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV3:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v3(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV3(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths_v3(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v2(payload)
