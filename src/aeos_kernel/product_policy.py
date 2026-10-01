"""The closed product-policy manifest: one schema, one canonical byte form, one typed view.

A product's policy is proposed as an immutable revision whose stored bytes are
``canonical_manifest_bytes_v1(payload)``. Every host reader turns those bytes back into a
``CanonicalProductManifest`` through ``load_canonical_manifest``, so the host database, API
and workers share this one parser instead of each keeping a reading of their own.
``CanonicalProductManifest.as_product_manifest`` adapts the typed view to the older
``ProductManifest`` the control plane already consumes.

Nothing here approves, activates or grants anything. The schema says what a well-formed
policy is; whether a revision is approved and current is the host ledger's fact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from aeos_kernel._validation import FrozenDict, freeze_json, thaw_json
from aeos_kernel.errors import ContractError
from aeos_kernel.registry import FcraPosture, Gating, LiabilityClass, ProductManifest

SCHEMA_VERSION: Final = "aeos.product-manifest.v1"
ACCEPTED_SCHEMA_VERSIONS: Final = frozenset({SCHEMA_VERSION})
READER_VERSION: Final = "1.0.0"
DIGEST_ALGORITHM: Final = "sha256"
CANONICALIZATION: Final = "canonical_manifest_bytes_v1"

#: The closed purpose union and the one principal class each purpose admits. A grant row whose
#: class differs from its purpose's class is refused, never re-mapped.
PURPOSE_PRINCIPAL_CLASSES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "authority_run": "authority_run_admission_service",
        "authority_probe": "authority_probe_worker",
        "authority_measurement": "authority_measurement_service",
        "channel_of_record": "channel_context_api",
        "content_freshness": "content_freshness_worker",
        "correction_deadline": "correction_intake_service",
        "publication_correction_gate": "publication_correction_service",
        "paid_plan": "marketing_result_evaluation_api",
        "paid_effect": "marketing_effects_worker",
        "model_call": "model_gateway_service",
        "credential_use": "external_gateway_service",
        "support_move_admission": "support_move_service",
        "renewal_action": "renewal_action_service",
        "sending_surface_evaluation": "sending_surface_service",
        "partner_quote_admission": "partner_quote_admission_service",
        "assistance_copy_adoption": "marketing_assistance_api",
        "outreach_copy_send": "distribution_worker",
        "email_program_activation": "marketing_email_worker",
        "readback": "product_policy_read_client",
    }
)
PURPOSES: Final = tuple(PURPOSE_PRINCIPAL_CLASSES)
#: Purposes that read policy and create no external-effect admission.
READ_ONLY_PURPOSES: Final = frozenset(
    {"authority_measurement", "channel_of_record", "paid_plan", "readback"}
)

#: The revocation sentinel. It names the whole revision and is never an approval section.
WHOLE_MANIFEST: Final = "whole_manifest"
#: The scope label under which the security/role owner withdraws a selected grant set, either
#: alongside a scoped revocation or through ``withdraw_latest_service_grant_set``.
SERVICE_GRANT_WITHDRAWAL: Final = "service_grant_withdrawal"


class ManifestReason(StrEnum):
    SCHEMA_INVALID = "manifest_schema_invalid"
    GRANT_MISMATCH = "manifest_grant_mismatch"
    IDENTITY_MISMATCH = "manifest_identity_mismatch"
    INCOMPATIBLE = "manifest_incompatible"


class ManifestContractError(ContractError):
    """A manifest failed the closed schema; ``path`` names where, never the value."""

    def __init__(self, reason: ManifestReason, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.reason_code = reason.value
        self.path = path


#: Each approval section, the one authority class that may approve it, and the payload paths
#: it covers. Versioned with ``SCHEMA_VERSION``: changing it needs a new schema version and
#: cannot reinterpret a stored revision. Every payload leaf belongs to exactly one section.
SECTION_AUTHORITY_CLASSES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "product_scope": "product_owner",
        "portfolio_placement": "portfolio_owner",
        "service_principal_grants": "security_role",
        "credential_scopes": "security_role",
        "brand_tone": "brand_owner",
        "product_legal": "product_legal_owner",
        "budget": "finance_owner",
        "authority_targets": "authority_owner",
        "owned_audience": "privacy_legal_owner",
        "paid_fence": "brand_owner",
        "commercial_terms": "commercial_owner",
        "deliverability": "delivery_owner",
        "content_policy": "content_policy_owner",
        "correction_policy": "correction_policy_owner",
        "source_bindings": "support_owner",
        "release_compatibility": "release_owner",
        "aeos_companion": "aeos_policy_owner",
    }
)
SECTION_PATHS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "product_scope": (
            "product_instance_id",
            "manifest_version",
            "effective_interval",
            "modules_enabled",
        ),
        "portfolio_placement": ("portfolio_phase_revision_id", "authority.wedge"),
        "service_principal_grants": ("service_principal_grants",),
        "credential_scopes": ("credential_scopes",),
        "brand_tone": ("tone_profile.voice", "tone_profile.forbidden_phrases"),
        "product_legal": ("tone_profile.allowed_claim_templates", "fcra_posture"),
        "budget": ("budget_caps", "authority.probe_budget"),
        "authority_targets": (
            "authority.measurement_window_days",
            "authority.target_query_classes",
            "authority.answer_engines",
            "authority.citation_rate_floor",
            "authority.earned_citations_floor",
            "authority.source_diversity_min",
        ),
        "owned_audience": ("authority.owned_audience",),
        "paid_fence": ("authority.paid_fence",),
        "commercial_terms": (
            "commercial.unit_economics",
            "commercial.renewal_attention",
            "commercial.quote",
        ),
        "deliverability": ("commercial.deliverability",),
        "content_policy": ("content_policy",),
        "correction_policy": ("correction_policy",),
        "source_bindings": ("source_bindings",),
        "release_compatibility": ("schema_version", "compatibility"),
        "aeos_companion": (
            "gating",
            "liability_class",
            "approval_policy_ref",
            "release_policy",
            "wlg_sync_policy",
            "task_generation_policy",
            "family_overrides",
        ),
    }
)
POLICY_SECTIONS: Final = tuple(SECTION_AUTHORITY_CLASSES)

#: Capabilities a reader of this schema supports; a revision may require any subset.
READER_CAPABILITIES: Final = frozenset(
    {
        "aeos.product-manifest.v1",
        "canonical_manifest_bytes_v1",
        "service_principal_grant_set_digest_v1",
        "effective_interval_v1",
        "purpose_principal_class_matrix_v1",
    }
)

CORRECTION_CLOCKS: Final = frozenset({"calendar_days", "business_days"})

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_.:-]{0,127}")
_PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,199}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
_DECIMAL_INPUT = re.compile(r"\+?(\d+)(?:\.(\d+))?")
_INTEGER_INPUT = re.compile(r"([+-]?)(\d+)")
_CURRENCY = re.compile(r"[A-Z]{3}")

Validator = Callable[[Any, str], Any]


def _fail(path: str, message: str, reason: ManifestReason = ManifestReason.SCHEMA_INVALID) -> Any:
    raise ManifestContractError(reason, path, message)


def _string(value: Any, path: str, *, max_length: int = 2000) -> str:
    if not isinstance(value, str) or not value:
        _fail(path, "must be a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _fail(path, "contains an unpaired surrogate")
    if len(value) > max_length:
        _fail(path, f"is longer than {max_length} characters")
    return str(value)


def _reference(value: Any, path: str) -> str:
    text = _string(value, path, max_length=500)
    if text != text.strip() or any(not char.isprintable() for char in text):
        _fail(path, "must be a clean reference without surrounding space or control characters")
    return text


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        _fail(path, "must be a lowercase identifier")
    return str(value)


def _principal_id(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _PRINCIPAL.fullmatch(value):
        _fail(path, "must be a principal identifier without spaces")
    return str(value)


def _uuid(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        _fail(path, "must be a UUID string")
    return str(value).lower()


def _sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        _fail(path, "must be a SHA-256 hex digest")
    return str(value).lower()


def _timestamp(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        _fail(path, "must be a UTC RFC 3339 whole-second timestamp ending in Z")
    try:
        datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        _fail(path, "is not a real calendar time")
    return str(value)


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(path, "must be true or false")
    return bool(value)


def _integer(value: Any, path: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "must be a JSON integer")
    if value < minimum:
        _fail(path, f"must be at least {minimum}")
    return int(value)


def _positive(value: Any, path: str) -> int:
    return _integer(value, path, minimum=1)


def _nonnegative(value: Any, path: str) -> int:
    return _integer(value, path, minimum=0)


def canonical_decimal(value: Any, path: str = "decimal") -> str:
    """Normalize one nonnegative decimal string; JSON numbers are refused."""

    if not isinstance(value, str) or not (match := _DECIMAL_INPUT.fullmatch(value)):
        return str(_fail(path, 'must be a decimal string such as "0.25"'))
    whole = match.group(1).lstrip("0") or "0"
    fraction = (match.group(2) or "").rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def canonical_integer_string(value: Any, path: str = "integer", *, signed: bool) -> str:
    """Normalize one integer carried as a string, as money in minor units is."""

    if not isinstance(value, str) or not (match := _INTEGER_INPUT.fullmatch(value)):
        return str(_fail(path, 'must be an integer string such as "1500"'))
    sign, digits = match.group(1), match.group(2).lstrip("0") or "0"
    if sign == "-" and not signed:
        _fail(path, "must not be negative")
    return f"-{digits}" if sign == "-" and digits != "0" else digits


def _unit_decimal(value: Any, path: str) -> str:
    text = canonical_decimal(value, path)
    if Decimal(text) > 1:
        _fail(path, "must fall between 0 and 1")
    return text


def _signed_minor(value: Any, path: str) -> str:
    return canonical_integer_string(value, path, signed=True)


def _unsigned_minor(value: Any, path: str) -> str:
    return canonical_integer_string(value, path, signed=False)


def _semver(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        _fail(path, "must be a semantic version such as 1.0.0")
    return str(value)


def _object(
    fields: Mapping[str, Validator], *, nullable: frozenset[str] = frozenset()
) -> Validator:
    def validate(value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return dict(_fail(path, "must be an object"))
        unknown = sorted(set(value) - set(fields))
        missing = sorted(set(fields) - set(value))
        if unknown:
            _fail(f"{path}.{unknown[0]}", "is not a field of this schema")
        if missing:
            _fail(f"{path}.{missing[0]}", "is required")
        result: dict[str, Any] = {}
        for key, validator in fields.items():
            child = value[key]
            result[key] = (
                None if child is None and key in nullable else validator(child, f"{path}.{key}")
            )
        return result

    return validate


def _canonical_key(value: Any) -> bytes:
    return _serialize(value)


def _set_of(item: Validator, *, nonempty: bool = False) -> Validator:
    def validate(value: Any, path: str) -> list[Any]:
        if not isinstance(value, list):
            return list(_fail(path, "must be an array"))
        if nonempty and not value:
            _fail(path, "must not be empty")
        normalized = [item(entry, f"{path}[{index}]") for index, entry in enumerate(value)]
        unique = {_canonical_key(entry): entry for entry in normalized}
        return [unique[key] for key in sorted(unique)]

    return validate


def _ordered(item: Validator, *, identity: Callable[[Any], Any], nonempty: bool) -> Validator:
    def validate(value: Any, path: str) -> list[Any]:
        if not isinstance(value, list):
            return list(_fail(path, "must be an array"))
        if nonempty and not value:
            _fail(path, "must not be empty")
        normalized = [item(entry, f"{path}[{index}]") for index, entry in enumerate(value)]
        seen: set[Any] = set()
        for index, entry in enumerate(normalized):
            key = identity(entry)
            if key in seen:
                _fail(f"{path}[{index}]", "repeats an earlier entry; ordered lists never collapse")
            seen.add(key)
        return normalized

    return validate


def _map_of(value_validator: Validator) -> Validator:
    def validate(value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return dict(_fail(path, "must be an object"))
        return {
            _identifier(key, f"{path} key"): value_validator(child, f"{path}.{key}")
            for key, child in value.items()
        }

    return validate


def _budget_cap(value: Any, path: str) -> dict[str, Any]:
    if isinstance(value, Mapping) and "currency" not in value:
        cap = _object({"amount": canonical_decimal, "unit": _identifier, "window": _identifier})
        return dict(cap(value, path))
    cap = _object(
        {
            "amount": canonical_decimal,
            "unit": _identifier,
            "window": _identifier,
            "currency": _currency,
        }
    )
    return dict(cap(value, path))


def _currency(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
        _fail(path, "must be an ISO 4217 code such as USD")
    return str(value)


def _grant(value: Any, path: str) -> dict[str, str]:
    row = _object(
        {"purpose": _identifier, "principal_id": _principal_id, "principal_class": _identifier}
    )(value, path)
    expected = PURPOSE_PRINCIPAL_CLASSES.get(row["purpose"])
    if expected is None:
        _fail(f"{path}.purpose", "is not a registered purpose", ManifestReason.GRANT_MISMATCH)
    if row["principal_class"] != expected:
        _fail(
            f"{path}.principal_class",
            "is not the principal class registered for this purpose",
            ManifestReason.GRANT_MISMATCH,
        )
    return dict(row)


def _clock(value: Any, path: str) -> str:
    if value not in CORRECTION_CLOCKS:
        _fail(path, "must be calendar_days or business_days")
    return str(value)


def _enum(values: Iterable[str]) -> Validator:
    allowed = frozenset(values)

    def validate(value: Any, path: str) -> str:
        if value not in allowed:
            _fail(path, f"must be one of {', '.join(sorted(allowed))}")
        return str(value)

    return validate


def _schema_version(value: Any, path: str) -> str:
    if value not in ACCEPTED_SCHEMA_VERSIONS:
        _fail(
            path, "names a schema version this reader does not accept", ManifestReason.INCOMPATIBLE
        )
    return str(value)


def _gating_decimal(value: Any, path: str) -> str:
    text = canonical_decimal(value, path)
    if not 0 < Decimal(text) <= 1:
        _fail(path, "must fall in (0, 1]")
    return text


def _companion(value: Any, path: str) -> dict[str, Any]:
    """An AEOS companion policy object whose owner is outside this schema.

    Its keys stay open because its owner defines them, but its values must still have one
    byte form: non-integer numbers are refused and carried as decimal strings instead.
    """

    if not isinstance(value, Mapping):
        return dict(_fail(path, "must be an object"))
    return {
        _string(key, f"{path} key", max_length=200): _companion_value(child, f"{path}.{key}")
        for key, child in value.items()
    }


def _companion_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        return _string(value, path) if value else value
    if isinstance(value, list):
        return [_companion_value(child, f"{path}[{index}]") for index, child in enumerate(value)]
    if isinstance(value, Mapping):
        return _companion(value, path)
    return _fail(path, "must use a decimal string instead of a fractional JSON number")


_INTERVAL = _object(
    {"starts_at": _timestamp, "ends_before": _timestamp, "decision_ref": _reference},
    nullable=frozenset({"ends_before"}),
)
_PAID_FENCE = _object(
    {
        "allow_brand_terms": _boolean,
        "allow_category_terms": _boolean,
        "allow_third_party_operator_terms": _boolean,
        "brand_term_register_ref": _reference,
        "brand_term_register_digest": _sha256,
        "brand_term_register_version": _reference,
        "category_term_register_ref": _reference,
        "category_term_register_digest": _sha256,
        "category_term_register_version": _reference,
        "operator_term_register_ref": _reference,
        "operator_term_register_digest": _sha256,
        "operator_term_register_version": _reference,
    }
)
_AUTHORITY = _object(
    {
        "wedge": _boolean,
        "measurement_window_days": _positive,
        "target_query_classes": _ordered(
            _object({"id": _identifier, "question": _string}),
            identity=lambda row: row["id"],
            nonempty=True,
        ),
        "answer_engines": _set_of(_object({"id": _identifier}), nonempty=True),
        "citation_rate_floor": _unit_decimal,
        "earned_citations_floor": _nonnegative,
        "source_diversity_min": _positive,
        "probe_budget": _object(
            {
                "probes_per_engine_per_query_class_per_window": _positive,
                "permitted_model_refs": _set_of(_reference),
            }
        ),
        "owned_audience": _object(
            {
                "lawful_basis_policy": _reference,
                "suppression_list_ref": _reference,
                "double_opt_in": _boolean,
            }
        ),
        "paid_fence": _PAID_FENCE,
    }
)
_COMMERCIAL = _object(
    {
        "unit_economics": _object(
            {
                "contribution_window_days": _positive,
                "contribution_margin_floor_minor": _signed_minor,
            }
        ),
        "renewal_attention": _object({"review_lead_days": _positive}),
        "deliverability": _object(
            {
                "minimum_sent": _positive,
                "complaint_rate_stop": _unit_decimal,
                "bounce_rate_stop": _unit_decimal,
                "window_days": _positive,
            }
        ),
        "quote": _object({"second_signature_above_minor": _unsigned_minor}),
    }
)
_PAYLOAD = _object(
    {
        "schema_version": _schema_version,
        "product_instance_id": _uuid,
        "portfolio_phase_revision_id": _uuid,
        "manifest_version": _reference,
        "effective_interval": _INTERVAL,
        "service_principal_grants": _set_of(_grant),
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
            {"mailbox_registry": _object({"version": _reference, "digest": _sha256})}
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
    }
)


def _serialize(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _version_key(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def normalize_manifest_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate against the closed schema and return the normalized payload."""

    normalized = dict(_PAYLOAD(payload, "manifest"))
    interval = normalized["effective_interval"]
    if interval["ends_before"] is not None and interval["ends_before"] <= interval["starts_at"]:
        _fail("manifest.effective_interval.ends_before", "must be later than starts_at")
    compatibility = normalized["compatibility"]
    if _version_key(compatibility["max_reader"]) < _version_key(compatibility["min_reader"]):
        _fail("manifest.compatibility.max_reader", "must not be earlier than min_reader")
    return normalized


def canonical_manifest_bytes_v1(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    """The one canonical byte form: validated, normalized, sorted, no insignificant space.

    When the storing row's identity is supplied, the payload must carry the same product,
    phase and version; a payload for one product can never be stored under another.
    """

    normalized = normalize_manifest_payload(payload)
    expected = {
        "product_instance_id": product_id,
        "portfolio_phase_revision_id": phase_revision_id,
    }
    for key, value in expected.items():
        if value is not None and normalized[key] != str(value).lower():
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


def manifest_digest(canonical_bytes: bytes) -> str:
    return hashlib.sha256(canonical_bytes).hexdigest()


def service_principal_grant_set_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical grant array; it reproduces from the payload alone."""

    grants = normalize_manifest_payload(payload)["service_principal_grants"]
    return hashlib.sha256(_serialize(grants)).hexdigest()


def decode_strict_json(raw: bytes) -> dict[str, Any]:
    """Strict decode: UTF-8 only, no duplicate keys, no NaN, fractional numbers kept exact.

    Fractional JSON numbers decode to ``Decimal`` so the schema can refuse them by type
    rather than silently round them through a float.
    """

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return dict(_fail("manifest", "is not UTF-8"))
    if text.startswith("﻿"):
        _fail("manifest", "starts with a byte-order mark")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            duplicate = next(key for key in keys if keys.count(key) > 1)
            _fail(f"manifest key {duplicate!r}", "appears twice")
        return dict(items)

    def constant(name: str) -> Any:
        return _fail("manifest", f"contains {name}, which is not JSON")

    try:
        value = json.loads(
            text, object_pairs_hook=pairs, parse_float=Decimal, parse_constant=constant
        )
    except json.JSONDecodeError as error:
        return dict(_fail("manifest", f"is not valid JSON ({error.msg})"))
    if not isinstance(value, dict):
        _fail("manifest", "must be a JSON object")
    return dict(value)


@dataclass(frozen=True, slots=True)
class ServiceGrant:
    purpose: str
    principal_id: str
    principal_class: str


@dataclass(frozen=True, slots=True)
class CanonicalProductManifest:
    """One validated revision payload with its canonical bytes and both digests."""

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

    def effective_at(self, instant: datetime) -> bool:
        """The interval is half-open: in force from its start, gone at ``ends_before``."""

        until = self.effective_until
        return self.effective_from <= instant and (until is None or instant < until)

    def grants_principal(self, *, purpose: str, principal_id: str, principal_class: str) -> bool:
        """Exact tuple membership; class membership never grants an unnamed identity."""

        return ServiceGrant(purpose, principal_id, principal_class) in self.grants

    def reader_compatible(self, reader_version: str = READER_VERSION) -> bool:
        compatibility = self.payload["compatibility"]
        version = _version_key(reader_version)
        return (
            _version_key(compatibility["min_reader"])
            <= version
            <= _version_key(compatibility["max_reader"])
            and set(compatibility["required_capabilities"]) <= READER_CAPABILITIES
        )

    def section(self, name: str) -> dict[str, Any]:
        """The payload paths one approval section covers, for review and readback."""

        if name not in SECTION_PATHS:
            raise ContractError(f"unknown policy section {name!r}")
        return {path: _at(self.payload, path) for path in SECTION_PATHS[name]}

    def as_product_manifest(self, product_slug: str) -> ProductManifest:
        """Adapt to the control plane's ``ProductManifest`` without inventing any value."""

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


def _parse_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _at(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        value = value[part]
    return thaw_json(value)


def load_canonical_manifest(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifest:
    """Parse raw bytes or a decoded mapping into the one typed view."""

    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v1(
        payload,
        product_id=product_id,
        phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifest(
        payload=freeze_json(normalized),
        canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(
            _serialize(normalized["service_principal_grants"])
        ).hexdigest(),
    )


def policy_leaf_paths(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Every top-level-or-section path in a normalized payload, for coverage checks."""

    paths: list[str] = []
    for key, value in payload.items():
        if key in {"authority", "commercial", "tone_profile"} and isinstance(value, Mapping):
            paths.extend(f"{key}.{child}" for child in value)
        else:
            paths.append(key)
    return tuple(sorted(paths))


__all__ = [
    "ACCEPTED_SCHEMA_VERSIONS",
    "CANONICALIZATION",
    "CORRECTION_CLOCKS",
    "DIGEST_ALGORITHM",
    "POLICY_SECTIONS",
    "PURPOSES",
    "PURPOSE_PRINCIPAL_CLASSES",
    "READER_CAPABILITIES",
    "READER_VERSION",
    "READ_ONLY_PURPOSES",
    "SCHEMA_VERSION",
    "SECTION_AUTHORITY_CLASSES",
    "SECTION_PATHS",
    "SERVICE_GRANT_WITHDRAWAL",
    "WHOLE_MANIFEST",
    "CanonicalProductManifest",
    "ManifestContractError",
    "ManifestReason",
    "ServiceGrant",
    "canonical_decimal",
    "canonical_integer_string",
    "canonical_manifest_bytes_v1",
    "decode_strict_json",
    "load_canonical_manifest",
    "manifest_digest",
    "normalize_manifest_payload",
    "policy_leaf_paths",
    "service_principal_grant_set_digest",
]
