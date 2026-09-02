"""Append-only decision lifecycle and drift reopening."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aeos_kernel._validation import digest, required, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.vocabulary import DecisionStatus

_TRANSITIONS: dict[DecisionStatus, frozenset[DecisionStatus]] = {
    DecisionStatus.PROPOSED: frozenset(
        {
            DecisionStatus.ACCEPTED,
            DecisionStatus.HUMAN_REQUIRED,
            DecisionStatus.REFUSED,
            DecisionStatus.STALE,
            DecisionStatus.SUPERSEDED,
        }
    ),
    DecisionStatus.HUMAN_REQUIRED: frozenset(
        {
            DecisionStatus.ACCEPTED,
            DecisionStatus.REFUSED,
            DecisionStatus.STALE,
            DecisionStatus.SUPERSEDED,
        }
    ),
    DecisionStatus.ACCEPTED: frozenset(
        {
            DecisionStatus.APPLYING,
            DecisionStatus.VERIFIED_CLOSED,
            DecisionStatus.STALE,
            DecisionStatus.SUPERSEDED,
        }
    ),
    DecisionStatus.APPLYING: frozenset(
        {DecisionStatus.APPLIED, DecisionStatus.APPLY_FAILED, DecisionStatus.STALE}
    ),
    DecisionStatus.APPLY_FAILED: frozenset(
        {DecisionStatus.APPLYING, DecisionStatus.STALE, DecisionStatus.SUPERSEDED}
    ),
    DecisionStatus.APPLIED: frozenset(
        {DecisionStatus.VERIFIED_CLOSED, DecisionStatus.VERIFIER_FAILED, DecisionStatus.STALE}
    ),
    DecisionStatus.VERIFIER_FAILED: frozenset(
        {DecisionStatus.APPLIED, DecisionStatus.STALE, DecisionStatus.SUPERSEDED}
    ),
    DecisionStatus.VERIFIED_CLOSED: frozenset({DecisionStatus.STALE}),
    DecisionStatus.STALE: frozenset({DecisionStatus.SUPERSEDED}),
    DecisionStatus.REFUSED: frozenset({DecisionStatus.SUPERSEDED}),
    DecisionStatus.SUPERSEDED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    record_id: str
    decision_id: str
    decision_revision: int
    event_sequence: int
    status: DecisionStatus
    packet_digest: str
    recommendation_digest: str
    occurred_at: datetime
    previous_record_digest: str = ""
    attestation_id: str = ""
    effect_receipt_id: str = ""
    outcome_evidence_ids: tuple[str, ...] = ()
    reason: str = ""
    schema_version: str = "2"

    def __post_init__(self) -> None:
        required(self.record_id, "record_id")
        required(self.decision_id, "decision_id")
        if self.schema_version != "2":
            raise ContractError("unsupported decision-record schema version")
        if not isinstance(self.status, DecisionStatus):
            raise ContractError("decision status is not recognized")
        if self.decision_revision <= 0 or self.event_sequence <= 0:
            raise ContractError("decision revision and event sequence must be positive")
        digest(self.packet_digest, "packet_digest")
        digest(self.recommendation_digest, "recommendation_digest")
        if self.previous_record_digest:
            digest(self.previous_record_digest, "previous_record_digest")
        utc(self.occurred_at, "occurred_at")
        for name in ("attestation_id", "effect_receipt_id", "reason"):
            value = str(getattr(self, name))
            if value:
                required(value, name)
        if len(set(self.outcome_evidence_ids)) != len(self.outcome_evidence_ids):
            raise ContractError("outcome evidence identities must be unique")
        for outcome_id in self.outcome_evidence_ids:
            required(outcome_id, "outcome_evidence_id")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "decision_id": self.decision_id,
            "decision_revision": self.decision_revision,
            "event_sequence": self.event_sequence,
            "status": self.status.value,
            "packet_digest": self.packet_digest,
            "recommendation_digest": self.recommendation_digest,
            "occurred_at": self.occurred_at.isoformat(),
            "previous_record_digest": self.previous_record_digest,
            "attestation_id": self.attestation_id,
            "effect_receipt_id": self.effect_receipt_id,
            "outcome_evidence_ids": list(self.outcome_evidence_ids),
            "reason": self.reason,
        }

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())


def transition_record(
    current: DecisionRecord,
    *,
    to_status: DecisionStatus,
    occurred_at: datetime,
    expected_record_digest: str,
    attestation_id: str = "",
    effect_receipt_id: str = "",
    outcome_evidence_ids: tuple[str, ...] = (),
    reason: str = "",
) -> DecisionRecord:
    if current.digest != expected_record_digest:
        raise ContractError("decision compare-and-swap digest does not match current record")
    if to_status not in _TRANSITIONS[current.status]:
        raise ContractError(
            f"invalid lifecycle transition {current.status.value} -> {to_status.value}"
        )
    utc(occurred_at, "occurred_at")
    if occurred_at <= current.occurred_at:
        raise ContractError("lifecycle occurrence time must advance")
    next_attestation = attestation_id or current.attestation_id
    next_receipt = effect_receipt_id or current.effect_receipt_id
    next_outcomes = outcome_evidence_ids or current.outcome_evidence_ids
    if to_status is DecisionStatus.APPLIED and not next_receipt:
        raise ContractError("applied status requires an effect receipt")
    if to_status is DecisionStatus.VERIFIED_CLOSED and not (next_receipt or next_outcomes):
        raise ContractError("verified_closed requires effect or outcome verification evidence")
    if to_status in {
        DecisionStatus.APPLY_FAILED,
        DecisionStatus.VERIFIER_FAILED,
        DecisionStatus.STALE,
    } and not reason:
        raise ContractError(f"{to_status.value} requires a typed reason")
    record_identity = stable_fingerprint({"previous": current.digest, "status": to_status.value})
    return DecisionRecord(
        record_id=f"record_{record_identity[:24]}",
        decision_id=current.decision_id,
        decision_revision=current.decision_revision,
        event_sequence=current.event_sequence + 1,
        status=to_status,
        packet_digest=current.packet_digest,
        recommendation_digest=current.recommendation_digest,
        occurred_at=occurred_at,
        previous_record_digest=current.digest,
        attestation_id=next_attestation,
        effect_receipt_id=next_receipt,
        outcome_evidence_ids=next_outcomes,
        reason=reason,
    )


def reopen_record(
    current: DecisionRecord,
    *,
    packet_digest: str,
    recommendation_digest: str,
    occurred_at: datetime,
    drift_reason: str,
) -> DecisionRecord:
    if current.status is not DecisionStatus.STALE:
        raise ContractError("only a stale decision can be reopened")
    required(drift_reason, "drift_reason")
    digest(packet_digest, "packet_digest")
    digest(recommendation_digest, "recommendation_digest")
    utc(occurred_at, "occurred_at")
    if occurred_at <= current.occurred_at:
        raise ContractError("reopen occurrence time must advance")
    if (
        packet_digest == current.packet_digest
        and recommendation_digest == current.recommendation_digest
    ):
        raise ContractError("reopening requires a material decision input change")
    record_identity = stable_fingerprint({"previous": current.digest, "packet": packet_digest})
    return DecisionRecord(
        record_id=f"record_{record_identity[:24]}",
        decision_id=current.decision_id,
        decision_revision=current.decision_revision + 1,
        event_sequence=1,
        status=DecisionStatus.PROPOSED,
        packet_digest=packet_digest,
        recommendation_digest=recommendation_digest,
        occurred_at=occurred_at,
        previous_record_digest=current.digest,
        reason=drift_reason,
    )
