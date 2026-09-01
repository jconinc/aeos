"""Typed AEOS failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RefusalCode(StrEnum):
    INVALID_PACKET = "invalid_packet"
    INVALID_EVIDENCE = "invalid_evidence"
    STALE_INPUT = "stale_input"
    CROSS_SCOPE_EVIDENCE = "cross_scope_evidence"
    AUTHORITY_MISSING = "authority_missing"
    AUTHORITY_CONFLICT = "authority_conflict"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    AMBIGUOUS_ENTAILMENT = "ambiguous_entailment"
    MODEL_REQUIRED = "model_required"
    MODEL_INVALID = "model_invalid"
    MODEL_DISAGREEMENT = "model_disagreement"
    MODEL_BUDGET_EXCEEDED = "model_budget_exceeded"
    HUMAN_REQUIRED = "human_required"
    HUMAN_ATTESTATION_INVALID = "human_attestation_invalid"
    BOUNDARY_NOT_AUTHORIZED = "boundary_not_authorized"
    EFFECT_NOT_REGISTERED = "effect_not_registered"
    EFFECT_PRECONDITION_FAILED = "effect_precondition_failed"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class Refusal:
    code: RefusalCode
    reason: str
    missing_premise: str = ""

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("refusal reason must be nonempty")


class ContractError(ValueError):
    """A public contract is malformed or internally inconsistent."""
