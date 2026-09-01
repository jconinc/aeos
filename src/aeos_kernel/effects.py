"""Host effect authorization, execution receipt, and outcome contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import digest, required, utc
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
    parameters: dict[str, Any]
    boundary_tags: tuple[str, ...]
    precondition_digest: str
    expected_postcondition: str
    idempotency_key: str
    authorized_at: datetime
    authority_policy_digest: str
    attestation_id: str = ""
    compensation_ref: str = ""
    cost_ceiling_minor_units: int = 0

    def __post_init__(self) -> None:
        for name in ("authorization_id", "decision_id", "operation", "idempotency_key"):
            required(str(getattr(self, name)), name)
        if self.decision_revision <= 0:
            raise ContractError("decision_revision must be positive")
        digest(self.precondition_digest, "precondition_digest")
        digest(self.authority_policy_digest, "authority_policy_digest")
        utc(self.authorized_at, "authorized_at")
        if self.cost_ceiling_minor_units < 0:
            raise ContractError("cost ceiling must be nonnegative")
        stable_fingerprint(self.parameters)
        object.__setattr__(self, "parameters", dict(self.parameters))

    @property
    def request_digest(self) -> str:
        return stable_fingerprint(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["authorized_at"] = self.authorized_at.isoformat()
        value["boundary_tags"] = list(self.boundary_tags)
        return value


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    receipt_id: str
    authorization_id: str
    decision_id: str
    decision_revision: int
    operation: str
    request_digest: str
    status: EffectStatus
    applied_at: datetime
    result_refs: tuple[str, ...] = ()
    actual_postimage_digest: str = ""
    external_confirmation_ref: str = ""
    safe_diagnostic: str = ""

    def __post_init__(self) -> None:
        for name in ("receipt_id", "authorization_id", "decision_id", "operation"):
            required(str(getattr(self, name)), name)
        if self.decision_revision <= 0:
            raise ContractError("decision_revision must be positive")
        digest(self.request_digest, "request_digest")
        utc(self.applied_at, "applied_at")
        if self.actual_postimage_digest:
            digest(self.actual_postimage_digest, "actual_postimage_digest")

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
        if self.policy_digest:
            digest(self.policy_digest, "policy_digest")
        if self.evidence_digest:
            digest(self.evidence_digest, "evidence_digest")
        stable_fingerprint(self.aggregate)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["window_started_at"] = self.window_started_at.isoformat()
        value["window_ended_at"] = self.window_ended_at.isoformat()
        value["observed_at"] = self.observed_at.isoformat()
        return value
