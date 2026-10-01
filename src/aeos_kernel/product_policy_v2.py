"""PB-195 v2 product manifest for correction-sweep admission.

This is deliberately a separate reader from :mod:`aeos_kernel.product_policy`.
Its schema, byte form and reader capabilities name the additional sweep contract; it
does not reinterpret v1 revisions or approve a policy, grant or activation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aeos_kernel._validation import FrozenDict, freeze_json, thaw_json
from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    _AUTHORITY,
    _COMMERCIAL,
    _INTERVAL,
    DIGEST_ALGORITHM,
    PURPOSE_PRINCIPAL_CLASSES,
    SECTION_AUTHORITY_CLASSES,
    SECTION_PATHS,
    ManifestContractError,
    ManifestReason,
    ServiceGrant,
    _at,
    _boolean,
    _budget_cap,
    _clock,
    _companion,
    _enum,
    _fail,
    _gating_decimal,
    _identifier,
    _map_of,
    _nonnegative,
    _object,
    _ordered,
    _parse_time,
    _positive,
    _principal_id,
    _reference,
    _semver,
    _serialize,
    _set_of,
    _sha256,
    _string,
    _uuid,
    _version_key,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.registry import FcraPosture, Gating, LiabilityClass, ProductManifest

SCHEMA_VERSION_V2: Final = "aeos.product-manifest.v2"
ACCEPTED_SCHEMA_VERSIONS_V2: Final = frozenset({SCHEMA_VERSION_V2})
READER_VERSION_V2: Final = "2.0.0"
CANONICALIZATION_V2: Final = "canonical_manifest_bytes_v2"

# The scope is deliberately separate from mailbox routing.  The principal identifier in a
# manifest remains a security/role decision; this class only makes its purpose unambiguous.
SWEEP_SCOPE: Final = "support:correction_sweep"
SWEEP_CAPABILITY: Final = "run_correction_sweep"
SWEEP_PURPOSE: Final = "correction_sweep"
SWEEP_PRINCIPAL_CLASS: Final = "correction_sweep_service"

PURPOSE_PRINCIPAL_CLASSES_V2: Final[Mapping[str, str]] = MappingProxyType(
    {**PURPOSE_PRINCIPAL_CLASSES, SWEEP_PURPOSE: SWEEP_PRINCIPAL_CLASS}
)

# A host can require every capability that its effectful consumer needs.  The reader only
# declares the capabilities it implements; a missing required capability is incompatible.
READER_CAPABILITIES_V2: Final = frozenset(
    {
        SCHEMA_VERSION_V2,
        CANONICALIZATION_V2,
        "purpose_principal_class_matrix_v2",
        "service_principal_grant_set_digest_v2",
        "effective_interval_v2",
    }
)
REQUIRED_SWEEP_HOST_CAPABILITIES_V2: Final = frozenset(
    {
        "support_manifest_scope_proposal_v2",
        "correction_sweep_source_binding_v2",
        "correction_sweep_queue_admission_v2",
        "correction_sweep_worker_revalidation_v2",
    }
)

SECTION_AUTHORITY_CLASSES_V2: Final[Mapping[str, str]] = MappingProxyType(
    {
        **SECTION_AUTHORITY_CLASSES,
        "source_sweep_source": "source_policy_owner",
        "source_sweep_privacy": "privacy_legal_owner",
        "source_sweep_calendar": "calendar_policy_owner",
        "source_sweep_correction_owner": "correction_policy_owner",
    }
)
SECTION_PATHS_V2: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        **SECTION_PATHS,
        "source_sweep_source": (
            "correction_sweep.policy_id",
            "correction_sweep.version",
            "correction_sweep.effective_interval",
            "correction_sweep.source_policy_revisions",
            "correction_sweep.fact_authority_rule",
        ),
        "source_sweep_privacy": (
            "correction_sweep.privacy_policy_refs",
            "correction_sweep.retention_policy_ref",
            "correction_sweep.access_policy_ref",
            "correction_sweep.legal_hold_policy_ref",
            "correction_sweep.incident_policy_ref",
        ),
        "source_sweep_calendar": (
            "correction_sweep.calendar",
            "correction_sweep.lookback_months",
            "correction_sweep.lookback_algorithm_version",
        ),
        "source_sweep_correction_owner": ("correction_sweep.correction_owner_policy_revision",),
    }
)
POLICY_SECTIONS_V2: Final = tuple(SECTION_AUTHORITY_CLASSES_V2)

_WEEKDAYS: Final = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)
_FOLD_RULES: Final = frozenset({"earlier", "later", "refuse"})
_GAP_RULES: Final = frozenset({"next_valid", "previous_valid", "refuse"})


def _schema_version_v2(value: Any, path: str) -> str:
    if value not in ACCEPTED_SCHEMA_VERSIONS_V2:
        _fail(
            path,
            "names a schema version this reader does not accept",
            ManifestReason.INCOMPATIBLE,
        )
    return str(value)


def _date(value: Any, path: str) -> str:
    text = _string(value, path, max_length=10)
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        _fail(path, "must be an ISO calendar date")
    return text


def _iana_time_zone(value: Any, path: str) -> str:
    text = _string(value, path, max_length=200)
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        _fail(path, "must name an installed IANA time zone")
    return text


def _sweep_grant(value: Any, path: str) -> dict[str, str]:
    row = _object(
        {"purpose": _identifier, "principal_id": _principal_id, "principal_class": _identifier}
    )(value, path)
    expected = PURPOSE_PRINCIPAL_CLASSES_V2.get(row["purpose"])
    if expected is None:
        _fail(f"{path}.purpose", "is not a registered purpose", ManifestReason.GRANT_MISMATCH)
    if row["principal_class"] != expected:
        _fail(
            f"{path}.principal_class",
            "is not the principal class registered for this purpose",
            ManifestReason.GRANT_MISMATCH,
        )
    return dict(row)


_CALENDAR = _object(
    {
        "artifact_id": _reference,
        "version": _reference,
        "digest": _sha256,
        "iana_time_zone": _iana_time_zone,
        "working_days": _set_of(_enum(_WEEKDAYS), nonempty=True),
        "holidays": _set_of(_date),
        "dst_fold_rule": _enum(_FOLD_RULES),
        "dst_gap_rule": _enum(_GAP_RULES),
    }
)
_CORRECTION_SWEEP = _object(
    {
        "policy_id": _reference,
        "version": _reference,
        "effective_interval": _INTERVAL,
        "source_policy_revisions": _set_of(_reference, nonempty=True),
        "fact_authority_rule": _reference,
        "privacy_policy_refs": _set_of(_reference, nonempty=True),
        "retention_policy_ref": _reference,
        "access_policy_ref": _reference,
        "legal_hold_policy_ref": _reference,
        "incident_policy_ref": _reference,
        "correction_owner_policy_revision": _reference,
        "calendar": _CALENDAR,
        "lookback_months": _positive,
        "lookback_algorithm_version": _reference,
    }
)
_PAYLOAD_V2 = _object(
    {
        "schema_version": _schema_version_v2,
        "product_instance_id": _uuid,
        "portfolio_phase_revision_id": _uuid,
        "manifest_version": _reference,
        "effective_interval": _INTERVAL,
        "service_principal_grants": _set_of(_sweep_grant),
        "modules_enabled": _set_of(_identifier, nonempty=True),
        "tone_profile": _object(
            {
                "voice": lambda value, path: _string(value, path, max_length=500),
                "forbidden_phrases": _ordered(_string, identity=lambda item: item, nonempty=False),
                "allowed_claim_templates": _ordered(
                    _reference, identity=lambda item: item, nonempty=False
                ),
            }
        ),
        "fcra_posture": _enum(item.value for item in FcraPosture),
        "credential_scopes": _map_of(_set_of(_identifier)),
        "budget_caps": _map_of(_budget_cap),
        "authority": _AUTHORITY,
        "commercial": _COMMERCIAL,
        "content_policy": _object({"review_age_days": _positive}),
        "correction_policy": _object(
            {
                "clock": _clock,
                "acknowledge_within_days": _nonnegative,
                "resolve_within_days": _nonnegative,
                "an_overdue_correction_stops_publication": _boolean,
            }
        ),
        "source_bindings": _object(
            {
                "mailbox_registry": _object({"version": _reference, "digest": _sha256}),
                "correction_sweep": _object({"version": _reference, "digest": _sha256}),
            }
        ),
        "compatibility": _object(
            {
                "min_reader": _semver,
                "max_reader": _semver,
                "required_capabilities": _set_of(_identifier),
            }
        ),
        "gating": _object(
            {
                "seed_approval_count": _nonnegative,
                "judgment_confidence_gate": _gating_decimal,
                "park_ttl_hours": _positive,
                "graduation_count": _positive,
                "stale_claim_days": _positive,
            }
        ),
        "liability_class": _enum(item.value for item in LiabilityClass),
        "approval_policy_ref": _reference,
        "release_policy": _companion,
        "wlg_sync_policy": _companion,
        "task_generation_policy": _companion,
        "family_overrides": _companion,
        "correction_sweep": _CORRECTION_SWEEP,
    }
)


def normalize_manifest_payload_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one closed v2 payload and keep the sweep capability out of mailbox scopes."""

    normalized = dict(_PAYLOAD_V2(payload, "manifest"))
    interval = normalized["effective_interval"]
    if interval["ends_before"] is not None and interval["ends_before"] <= interval["starts_at"]:
        _fail("manifest.effective_interval.ends_before", "must be later than starts_at")
    sweep_interval = normalized["correction_sweep"]["effective_interval"]
    if (
        sweep_interval["ends_before"] is not None
        and sweep_interval["ends_before"] <= sweep_interval["starts_at"]
    ):
        _fail(
            "manifest.correction_sweep.effective_interval.ends_before",
            "must be later than starts_at",
        )
    compatibility = normalized["compatibility"]
    if _version_key(compatibility["max_reader"]) < _version_key(compatibility["min_reader"]):
        _fail("manifest.compatibility.max_reader", "must not be earlier than min_reader")
    missing_capabilities = (READER_CAPABILITIES_V2 | REQUIRED_SWEEP_HOST_CAPABILITIES_V2) - set(
        compatibility["required_capabilities"]
    )
    if missing_capabilities:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v2 schema and sweep-host capability",
            ManifestReason.INCOMPATIBLE,
        )
    scope = normalized["credential_scopes"].get(SWEEP_SCOPE)
    if scope != [SWEEP_CAPABILITY]:
        _fail(
            f"manifest.credential_scopes.{SWEEP_SCOPE}",
            "must contain exactly the correction-sweep capability",
            ManifestReason.GRANT_MISMATCH,
        )
    for scope_name, capabilities in normalized["credential_scopes"].items():
        if scope_name != SWEEP_SCOPE and SWEEP_CAPABILITY in capabilities:
            _fail(
                f"manifest.credential_scopes.{scope_name}",
                "must not carry the correction-sweep capability",
                ManifestReason.GRANT_MISMATCH,
            )
    grants = normalized["service_principal_grants"]
    if sum(grant["purpose"] == SWEEP_PURPOSE for grant in grants) != 1:
        _fail(
            "manifest.service_principal_grants",
            "must contain exactly one dedicated correction-sweep principal grant",
            ManifestReason.GRANT_MISMATCH,
        )
    return normalized


def canonical_manifest_bytes_v2(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    """Return v2's sole canonical byte form after identity-bound validation."""

    normalized = normalize_manifest_payload_v2(payload)
    expected = {
        "product_instance_id": product_id,
        "portfolio_phase_revision_id": phase_revision_id,
    }
    for key, value in expected.items():
        if value is not None and normalized[key] != str(value).lower():
            _fail(
                f"manifest.{key}",
                "differs from the revision row",
                ManifestReason.IDENTITY_MISMATCH,
            )
    if manifest_version is not None and normalized["manifest_version"] != manifest_version:
        _fail(
            "manifest.manifest_version",
            "differs from the revision row",
            ManifestReason.IDENTITY_MISMATCH,
        )
    return _serialize(normalized)


def service_principal_grant_set_digest_v2(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the normalized v2 service-principal grant array."""

    grants = normalize_manifest_payload_v2(payload)["service_principal_grants"]
    return hashlib.sha256(_serialize(grants)).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalProductManifestV2:
    """Validated v2 payload, canonical bytes and exact grant identities."""

    payload: FrozenDict
    canonical_bytes: bytes
    manifest_digest: str
    grant_set_digest: str

    @property
    def product_instance_id(self) -> str:
        return str(self.payload["product_instance_id"])

    @property
    def portfolio_phase_revision_id(self) -> str:
        return str(self.payload["portfolio_phase_revision_id"])

    @property
    def manifest_version(self) -> str:
        return str(self.payload["manifest_version"])

    @property
    def effective_from(self) -> datetime:
        return _parse_time(self.payload["effective_interval"]["starts_at"])

    @property
    def effective_until(self) -> datetime | None:
        ends = self.payload["effective_interval"]["ends_before"]
        return None if ends is None else _parse_time(ends)

    @property
    def effective_time_decision_ref(self) -> str:
        return str(self.payload["effective_interval"]["decision_ref"])

    @property
    def wedge(self) -> bool:
        return bool(self.payload["authority"]["wedge"])

    @property
    def compatibility(self) -> dict[str, Any]:
        return dict(thaw_json(self.payload["compatibility"]))

    @property
    def grants(self) -> tuple[ServiceGrant, ...]:
        return tuple(ServiceGrant(**dict(row)) for row in self.payload["service_principal_grants"])

    @property
    def correction_sweep(self) -> dict[str, Any]:
        return dict(thaw_json(self.payload["correction_sweep"]))

    @property
    def correction_sweep_source_binding(self) -> dict[str, str]:
        return dict(thaw_json(self.payload["source_bindings"]["correction_sweep"]))

    def effective_at(self, instant: datetime) -> bool:
        until = self.effective_until
        return self.effective_from <= instant and (until is None or instant < until)

    def grants_principal(self, *, purpose: str, principal_id: str, principal_class: str) -> bool:
        return ServiceGrant(purpose, principal_id, principal_class) in self.grants

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V2,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        """Check schema and explicitly supplied installed host capabilities.

        The default has only the AEOS reader's capabilities, so an effectful v2 policy remains
        unavailable until the host confirms its source-binding, admission and worker checks.
        """

        compatibility = self.payload["compatibility"]
        version = _version_key(reader_version)
        return _version_key(compatibility["min_reader"]) <= version <= _version_key(
            compatibility["max_reader"]
        ) and set(compatibility["required_capabilities"]) <= READER_CAPABILITIES_V2 | set(
            available_capabilities
        )

    def section(self, name: str) -> dict[str, Any]:
        if name not in SECTION_PATHS_V2:
            raise ContractError(f"unknown policy section {name!r}")
        return {path: _at(self.payload, path) for path in SECTION_PATHS_V2[name]}

    def as_product_manifest(self, product_slug: str) -> ProductManifest:
        """Carry the v1 host-facing control-plane fields without defaulting any value."""

        payload = thaw_json(self.payload)
        gating = dict(payload["gating"])
        gating["judgment_confidence_gate"] = float(Decimal(gating["judgment_confidence_gate"]))
        return ProductManifest(
            product_slug=product_slug,
            version=self.manifest_version,
            modules_enabled=tuple(payload["modules_enabled"]),
            tone_profile=payload["tone_profile"],
            fcra_posture=FcraPosture(payload["fcra_posture"]),
            credential_scopes=payload["credential_scopes"],
            budget_caps=payload["budget_caps"],
            gating=Gating(**gating),
            liability_class=LiabilityClass(payload["liability_class"]),
            approval_policy_ref=payload["approval_policy_ref"],
            release_policy=payload["release_policy"],
            wlg_sync_policy=payload["wlg_sync_policy"],
            task_generation_policy=payload["task_generation_policy"],
            family_overrides=payload["family_overrides"],
        )


def load_canonical_manifest_v2(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV2:
    """Parse raw v2 bytes or a decoded mapping into its immutable typed view."""

    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v2(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV2(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths_v2(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return v2 approval leaves; the calendar is one owner-controlled policy object."""

    paths: list[str] = []
    for key, value in payload.items():
        if key in {"authority", "commercial", "tone_profile", "correction_sweep"} and isinstance(
            value, Mapping
        ):
            paths.extend(f"{key}.{child}" for child in value)
        else:
            paths.append(key)
    return tuple(sorted(paths))


__all__ = [
    "ACCEPTED_SCHEMA_VERSIONS_V2",
    "CANONICALIZATION_V2",
    "DIGEST_ALGORITHM",
    "POLICY_SECTIONS_V2",
    "PURPOSE_PRINCIPAL_CLASSES_V2",
    "READER_CAPABILITIES_V2",
    "READER_VERSION_V2",
    "REQUIRED_SWEEP_HOST_CAPABILITIES_V2",
    "SCHEMA_VERSION_V2",
    "SECTION_AUTHORITY_CLASSES_V2",
    "SECTION_PATHS_V2",
    "SWEEP_CAPABILITY",
    "SWEEP_PRINCIPAL_CLASS",
    "SWEEP_PURPOSE",
    "SWEEP_SCOPE",
    "CanonicalProductManifestV2",
    "ManifestContractError",
    "ManifestReason",
    "canonical_manifest_bytes_v2",
    "load_canonical_manifest_v2",
    "normalize_manifest_payload_v2",
    "policy_leaf_paths_v2",
    "service_principal_grant_set_digest_v2",
]
