"""Decision subject, evidence, authority-policy, and packet contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from aeos_kernel._validation import (
    digest,
    immutable_json_object,
    required,
    thaw_json,
    utc,
)
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.vocabulary import AuthorityLevel, DecisionIntensity, PrivacyClass

SCHEMA_VERSION = "2"


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_type: str
    source_id: str
    revision: str
    digest: str

    def __post_init__(self) -> None:
        required(self.source_type, "source_type")
        required(self.source_id, "source_id")
        required(self.revision, "revision")
        digest(self.digest, "digest")


@dataclass(frozen=True, slots=True)
class DecisionSubject:
    vertical_id: str
    tenant_id: str
    subject_id: str
    subject_kind: str
    revision: str
    content_digest: str
    attributes: dict[str, Any] = field(default_factory=dict)
    source_refs: tuple[SourceRef, ...] = ()
    privacy_classification: PrivacyClass = PrivacyClass.INTERNAL
    allowed_uses: tuple[str, ...] = ("decision",)

    def __post_init__(self) -> None:
        for name in ("vertical_id", "tenant_id", "subject_id", "subject_kind", "revision"):
            required(str(getattr(self, name)), name)
        digest(self.content_digest, "content_digest")
        if not self.allowed_uses:
            raise ContractError("subject allowed_uses must be nonempty")
        if len(set(self.allowed_uses)) != len(self.allowed_uses):
            raise ContractError("subject allowed_uses must be unique")
        for use in self.allowed_uses:
            required(use, "subject allowed use")
        if not self.source_refs:
            raise ContractError("subject source_refs must be nonempty")
        source_identities = {
            (item.source_type, item.source_id, item.revision) for item in self.source_refs
        }
        if len(source_identities) != len(self.source_refs):
            raise ContractError("subject source references must be unique")
        object.__setattr__(
            self,
            "attributes",
            immutable_json_object(self.attributes, "subject attributes"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "vertical_id": self.vertical_id,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "attributes": thaw_json(self.attributes),
            "source_refs": [asdict(item) for item in self.source_refs],
            "privacy_classification": self.privacy_classification.value,
            "allowed_uses": list(self.allowed_uses),
        }


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    evidence_digest: str
    source_tier: str
    vertical_id: str
    tenant_id: str
    subject_id: str
    subject_revision: str
    payload: dict[str, Any]
    source_ref: SourceRef
    observed_at: datetime
    expires_at: datetime | None = None
    privacy_classification: PrivacyClass = PrivacyClass.INTERNAL
    allowed_uses: tuple[str, ...] = ("decision",)
    research_receipt_digest: str = ""

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "source_tier",
            "vertical_id",
            "tenant_id",
            "subject_id",
            "subject_revision",
        ):
            required(str(getattr(self, name)), name)
        digest(self.evidence_digest, "evidence_digest")
        utc(self.observed_at, "observed_at")
        if self.expires_at is not None:
            utc(self.expires_at, "expires_at")
        if self.research_receipt_digest:
            digest(self.research_receipt_digest, "research_receipt_digest")
        if not self.allowed_uses:
            raise ContractError("evidence allowed_uses must be nonempty")
        if len(set(self.allowed_uses)) != len(self.allowed_uses):
            raise ContractError("evidence allowed_uses must be unique")
        for use in self.allowed_uses:
            required(use, "evidence allowed use")
        object.__setattr__(
            self,
            "payload",
            immutable_json_object(self.payload, "evidence payload"),
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_tier": self.source_tier,
            "vertical_id": self.vertical_id,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "subject_revision": self.subject_revision,
            "payload": thaw_json(self.payload),
            "source_ref": asdict(self.source_ref),
            "observed_at": self.observed_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "privacy_classification": self.privacy_classification.value,
            "allowed_uses": list(self.allowed_uses),
            "research_receipt_digest": self.research_receipt_digest,
        }

    def has_canonical_digest(self) -> bool:
        return self.evidence_digest == stable_fingerprint(self.canonical_payload())

    def as_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "evidence_digest": self.evidence_digest}


def build_evidence_item(**values: Any) -> EvidenceItem:
    provisional = EvidenceItem(evidence_digest="0" * 64, **values)
    return EvidenceItem(
        **{**values, "evidence_digest": stable_fingerprint(provisional.canonical_payload())}
    )


@dataclass(frozen=True, slots=True)
class AuthorityPolicy:
    policy_id: str
    policy_version: str
    level: AuthorityLevel
    intensity: DecisionIntensity
    allowed_boundary_tags: tuple[str, ...] = ()
    required_capacity: str = ""
    requires_human_attestation: bool = False
    permits_model_choice: bool = False
    max_model_calls: int = 0
    max_model_cost_minor_units: int = 0
    model_provider: str = ""
    model_id: str = ""
    model_context_classification: str = ""
    model_generation_parameters_digest: str = ""

    def __post_init__(self) -> None:
        required(self.policy_id, "policy_id")
        required(self.policy_version, "policy_version")
        if not isinstance(self.level, AuthorityLevel):
            raise ContractError("authority level is not recognized")
        if not isinstance(self.intensity, DecisionIntensity):
            raise ContractError("decision intensity is not recognized")
        if len(set(self.allowed_boundary_tags)) != len(self.allowed_boundary_tags):
            raise ContractError("allowed boundary tags must be unique")
        for tag in self.allowed_boundary_tags:
            required(tag, "allowed boundary tag")
        if self.requires_human_attestation and not self.required_capacity:
            raise ContractError("human attestation requires a named capacity")
        if self.max_model_calls < 0 or self.max_model_cost_minor_units < 0:
            raise ContractError("model budgets must be nonnegative")
        model_identity = (
            self.model_provider,
            self.model_id,
            self.model_context_classification,
            self.model_generation_parameters_digest,
        )
        if self.permits_model_choice:
            if self.level is not AuthorityLevel.AGENT_JUDGMENT:
                raise ContractError("model choice requires agent_judgment authority")
            if self.max_model_calls <= 0:
                raise ContractError("model choice requires a positive call ceiling")
            for name, value in zip(
                (
                    "model_provider",
                    "model_id",
                    "model_context_classification",
                ),
                model_identity[:3],
                strict=True,
            ):
                required(value, name)
            digest(
                self.model_generation_parameters_digest,
                "model_generation_parameters_digest",
            )
        elif self.max_model_calls or self.max_model_cost_minor_units or any(model_identity):
            raise ContractError("model controls cannot be set when model choice is forbidden")
        if self.level is AuthorityLevel.HUMAN_REQUIRED and not self.requires_human_attestation:
            raise ContractError("human_required authority requires human attestation")

    def as_dict(self) -> dict[str, Any]:
        value = {
            **asdict(self),
            "level": self.level.value,
            "intensity": int(self.intensity),
            "allowed_boundary_tags": list(self.allowed_boundary_tags),
        }
        if not self.permits_model_choice:
            for name in (
                "model_provider",
                "model_id",
                "model_context_classification",
                "model_generation_parameters_digest",
            ):
                value.pop(name)
        return value


@dataclass(frozen=True, slots=True)
class DecisionPacket:
    packet_id: str
    packet_digest: str
    subject: DecisionSubject
    evidence: tuple[EvidenceItem, ...]
    authority_bundle_digest: str
    policy: AuthorityPolicy
    allowed_actions: tuple[str, ...]
    source_head_pins: dict[str, str]
    adapter_id: str
    adapter_version: str
    created_at: datetime
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("packet_id", "adapter_id", "adapter_version", "schema_version"):
            required(str(getattr(self, name)), name)
        digest(self.packet_digest, "packet_digest")
        digest(self.authority_bundle_digest, "authority_bundle_digest")
        utc(self.created_at, "created_at")
        if not self.allowed_actions:
            raise ContractError("allowed_actions must be nonempty")
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ContractError("allowed_actions must be unique")
        if not self.source_head_pins:
            raise ContractError("source_head_pins must be nonempty")
        for name, value in self.source_head_pins.items():
            required(name, "source head name")
            # Git SHA-1, SHA-256, database snapshot IDs, and signed provider
            # cursors are all legitimate host pins. Their verifier owns the
            # format; the kernel only refuses an absent or malformed string.
            required(value, f"source_head_pins[{name!r}]")
        object.__setattr__(
            self,
            "source_head_pins",
            immutable_json_object(self.source_head_pins, "source_head_pins"),
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "packet_id": self.packet_id,
            "subject": self.subject.as_dict(),
            "evidence": [item.as_dict() for item in self.evidence],
            "authority_bundle_digest": self.authority_bundle_digest,
            "policy": self.policy.as_dict(),
            "allowed_actions": list(self.allowed_actions),
            "source_head_pins": thaw_json(self.source_head_pins),
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "created_at": self.created_at.isoformat(),
        }

    def has_canonical_digest(self) -> bool:
        return self.packet_digest == stable_fingerprint(self.canonical_payload())

    def as_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "packet_digest": self.packet_digest}


def build_decision_packet(**values: Any) -> DecisionPacket:
    provisional = DecisionPacket(packet_digest="0" * 64, **values)
    return DecisionPacket(
        **{**values, "packet_digest": stable_fingerprint(provisional.canonical_payload())}
    )
