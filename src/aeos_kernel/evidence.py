"""Decision subject, evidence, authority-policy, and packet contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from aeos_kernel._validation import digest, required, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.vocabulary import AuthorityLevel, DecisionIntensity, PrivacyClass

SCHEMA_VERSION = "1"


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
        stable_fingerprint(self.attributes)
        object.__setattr__(self, "attributes", dict(self.attributes))

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["privacy_classification"] = self.privacy_classification.value
        value["source_refs"] = [asdict(item) for item in self.source_refs]
        value["allowed_uses"] = list(self.allowed_uses)
        return value


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
        stable_fingerprint(self.payload)
        object.__setattr__(self, "payload", dict(self.payload))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_tier": self.source_tier,
            "vertical_id": self.vertical_id,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "subject_revision": self.subject_revision,
            "payload": self.payload,
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

    def __post_init__(self) -> None:
        required(self.policy_id, "policy_id")
        required(self.policy_version, "policy_version")
        if self.requires_human_attestation and not self.required_capacity:
            raise ContractError("human attestation requires a named capacity")
        if self.max_model_calls < 0 or self.max_model_cost_minor_units < 0:
            raise ContractError("model budgets must be nonnegative")
        if not self.permits_model_choice and self.max_model_calls:
            raise ContractError("model calls cannot be budgeted when model choice is forbidden")

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "level": self.level.value,
            "intensity": int(self.intensity),
            "allowed_boundary_tags": list(self.allowed_boundary_tags),
        }


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
        object.__setattr__(self, "source_head_pins", dict(self.source_head_pins))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "packet_id": self.packet_id,
            "subject": self.subject.as_dict(),
            "evidence": [item.as_dict() for item in self.evidence],
            "authority_bundle_digest": self.authority_bundle_digest,
            "policy": self.policy.as_dict(),
            "allowed_actions": list(self.allowed_actions),
            "source_head_pins": self.source_head_pins,
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
