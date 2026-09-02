"""Host effect authorization, execution receipt, and outcome contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, thaw_json, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError


class EffectStatus(StrEnum):
    APPLIED = "applied"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class OutcomeStatus(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class AuthorizedEffect:
    authorization_id: str
    decision_id: str
    decision_revision: int
    operation: str
    operation_version: str
    operation_contract_digest: str
    parameters: dict[str, Any]
    boundary_tags: tuple[str, ...]
    precondition_digest: str
    expected_postcondition: str
    idempotency_key: str
    authorized_at: datetime
    authority_policy_digest: str
    recommendation_digest: str
    candidate_set_digest: str
    projection_digest: str
    source_head_pins_digest: str
    attestation_id: str = ""
    attestation_digest: str = ""
    compensation_ref: str = ""
    cost_ceiling_minor_units: int = 0

    def __post_init__(self) -> None:
        for name in (
            "authorization_id",
            "decision_id",
            "operation",
            "operation_version",
            "idempotency_key",
        ):
            required(str(getattr(self, name)), name)
        if self.decision_revision <= 0:
            raise ContractError("decision_revision must be positive")
        digest(self.precondition_digest, "precondition_digest")
        for name in (
            "operation_contract_digest",
            "authority_policy_digest",
            "recommendation_digest",
            "candidate_set_digest",
            "projection_digest",
            "source_head_pins_digest",
        ):
            digest(str(getattr(self, name)), name)
        if self.attestation_id:
            digest(self.attestation_digest, "attestation_digest")
        elif self.attestation_digest:
            raise ContractError("attestation digest requires an attestation identity")
        utc(self.authorized_at, "authorized_at")
        if self.cost_ceiling_minor_units < 0:
            raise ContractError("cost ceiling must be nonnegative")
        object.__setattr__(
            self,
            "parameters",
            immutable_json_object(self.parameters, "authorized effect parameters"),
        )

    @property
    def request_digest(self) -> str:
        return stable_fingerprint(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "decision_id": self.decision_id,
            "decision_revision": self.decision_revision,
            "operation": self.operation,
            "operation_version": self.operation_version,
            "operation_contract_digest": self.operation_contract_digest,
            "parameters": thaw_json(self.parameters),
            "boundary_tags": list(self.boundary_tags),
            "precondition_digest": self.precondition_digest,
            "expected_postcondition": self.expected_postcondition,
            "idempotency_key": self.idempotency_key,
            "authorized_at": self.authorized_at.isoformat(),
            "authority_policy_digest": self.authority_policy_digest,
            "recommendation_digest": self.recommendation_digest,
            "candidate_set_digest": self.candidate_set_digest,
            "projection_digest": self.projection_digest,
            "source_head_pins_digest": self.source_head_pins_digest,
            "attestation_id": self.attestation_id,
            "attestation_digest": self.attestation_digest,
            "compensation_ref": self.compensation_ref,
            "cost_ceiling_minor_units": self.cost_ceiling_minor_units,
        }


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    receipt_id: str
    authorization_id: str
    decision_id: str
    decision_revision: int
    operation: str
    operation_version: str
    request_digest: str
    status: EffectStatus
    applied_at: datetime
    result_refs: tuple[str, ...] = ()
    actual_postimage_digest: str = ""
    external_confirmation_ref: str = ""
    safe_diagnostic: str = ""

    def __post_init__(self) -> None:
        for name in (
            "receipt_id",
            "authorization_id",
            "decision_id",
            "operation",
            "operation_version",
        ):
            required(str(getattr(self, name)), name)
        if self.decision_revision <= 0:
            raise ContractError("decision_revision must be positive")
        digest(self.request_digest, "request_digest")
        utc(self.applied_at, "applied_at")
        if self.actual_postimage_digest:
            digest(self.actual_postimage_digest, "actual_postimage_digest")
        if self.external_confirmation_ref:
            required(self.external_confirmation_ref, "external_confirmation_ref")
        if len(set(self.result_refs)) != len(self.result_refs):
            raise ContractError("receipt result references must be unique")
        for result_ref in self.result_refs:
            required(result_ref, "receipt result reference")
        if len(self.safe_diagnostic) > 2_000:
            raise ContractError("safe diagnostic exceeds the 2000 character bound")
        if self.status is EffectStatus.APPLIED and not (
            self.result_refs or self.actual_postimage_digest or self.external_confirmation_ref
        ):
            raise ContractError("an applied receipt requires durable result evidence")
        if self.status is not EffectStatus.APPLIED and not self.safe_diagnostic:
            raise ContractError("a non-applied receipt requires a safe diagnostic")

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["applied_at"] = self.applied_at.isoformat()
        value["result_refs"] = list(self.result_refs)
        return value


@dataclass(frozen=True, slots=True)
class OutcomeEvidence:
    outcome_id: str
    receipt_id: str
    metric_id: str
    status: OutcomeStatus
    window_started_at: datetime
    window_ended_at: datetime
    observed_at: datetime
    aggregate: dict[str, Any] = field(default_factory=dict)
    policy_digest: str = ""
    evidence_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("outcome_id", "receipt_id", "metric_id"):
            required(str(getattr(self, name)), name)
        for name in ("window_started_at", "window_ended_at", "observed_at"):
            utc(getattr(self, name), name)
        if self.window_ended_at < self.window_started_at:
            raise ContractError("outcome window cannot end before it starts")
        digest(self.policy_digest, "policy_digest")
        digest(self.evidence_digest, "evidence_digest")
        object.__setattr__(
            self,
            "aggregate",
            immutable_json_object(self.aggregate, "outcome aggregate"),
        )
        if not self.has_canonical_digest():
            raise ContractError("outcome evidence_digest is not canonical")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "receipt_id": self.receipt_id,
            "metric_id": self.metric_id,
            "status": self.status.value,
            "window_started_at": self.window_started_at.isoformat(),
            "window_ended_at": self.window_ended_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "aggregate": thaw_json(self.aggregate),
            "policy_digest": self.policy_digest,
        }

    def has_canonical_digest(self) -> bool:
        return self.evidence_digest == stable_fingerprint(self.canonical_payload())

    def as_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "evidence_digest": self.evidence_digest}


def build_outcome_evidence(
    *,
    outcome_id: str,
    receipt_id: str,
    metric_id: str,
    status: OutcomeStatus,
    window_started_at: datetime,
    window_ended_at: datetime,
    observed_at: datetime,
    aggregate: dict[str, Any],
    policy_digest: str,
) -> OutcomeEvidence:
    """Build outcome evidence with the canonical evidence digest."""

    payload = {
        "outcome_id": outcome_id,
        "receipt_id": receipt_id,
        "metric_id": metric_id,
        "status": status.value,
        "window_started_at": window_started_at.isoformat(),
        "window_ended_at": window_ended_at.isoformat(),
        "observed_at": observed_at.isoformat(),
        "aggregate": thaw_json(aggregate),
        "policy_digest": policy_digest,
    }
    return OutcomeEvidence(
        outcome_id=outcome_id,
        receipt_id=receipt_id,
        metric_id=metric_id,
        status=status,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        observed_at=observed_at,
        aggregate=aggregate,
        policy_digest=policy_digest,
        evidence_digest=stable_fingerprint(payload),
    )
