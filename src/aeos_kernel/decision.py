"""Candidate, effect-template, model-call, and recommendation contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from aeos_kernel._validation import digest, required
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError, Refusal
from aeos_kernel.vocabulary import DecisionStatus


@dataclass(frozen=True, slots=True)
class EntailmentProof:
    source_tier: str
    cited_evidence_ids: tuple[str, ...]
    reason: str
    claimed_entailed: bool = False

    def __post_init__(self) -> None:
        required(self.source_tier, "source_tier")
        required(self.reason, "reason")
        if not self.cited_evidence_ids:
            raise ContractError("entailment proof must cite evidence")


@dataclass(frozen=True, slots=True)
class EffectTemplate:
    operation: str
    parameters: dict[str, Any]
    boundary_tags: tuple[str, ...]
    expected_postcondition: str
    reversible: bool
    compensation_ref: str = ""
    cost_ceiling_minor_units: int = 0

    def __post_init__(self) -> None:
        required(self.operation, "operation")
        required(self.expected_postcondition, "expected_postcondition")
        if self.cost_ceiling_minor_units < 0:
            raise ContractError("effect cost ceiling must be nonnegative")
        stable_fingerprint(self.parameters)
        object.__setattr__(self, "parameters", dict(self.parameters))


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    action: str
    title: str
    explanation: str
    proof: EntailmentProof
    expected_benefit: str = ""
    uncertainty: str = ""
    effect: EffectTemplate | None = None

    def __post_init__(self) -> None:
        for name in ("candidate_id", "action", "title", "explanation"):
            required(str(getattr(self, name)), name)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["proof"]["cited_evidence_ids"] = list(self.proof.cited_evidence_ids)
        if self.effect is not None:
            value["effect"]["boundary_tags"] = list(self.effect.boundary_tags)
        return value


def candidate_set_digest(candidates: tuple[Candidate, ...]) -> str:
    return stable_fingerprint([candidate.as_dict() for candidate in candidates])


@dataclass(frozen=True, slots=True)
class ModelCallIdentity:
    provider: str
    model_id: str
    prompt_digest: str
    generation_parameters_digest: str
    attempt: int
    cost_minor_units: int = 0

    def __post_init__(self) -> None:
        required(self.provider, "provider")
        required(self.model_id, "model_id")
        digest(self.prompt_digest, "prompt_digest")
        digest(self.generation_parameters_digest, "generation_parameters_digest")
        if self.attempt <= 0 or self.cost_minor_units < 0:
            raise ContractError("model attempt must be positive and cost nonnegative")


@dataclass(frozen=True, slots=True)
class ModelDecision:
    candidate_id: str
    rationale: str
    citations: tuple[str, ...]
    confidence: float
    identity: ModelCallIdentity
    retained_output: dict[str, Any]

    def __post_init__(self) -> None:
        required(self.candidate_id, "candidate_id")
        required(self.rationale, "rationale")
        if not self.citations:
            raise ContractError("model decision must cite evidence")
        if not 0 <= self.confidence <= 1:
            raise ContractError("model confidence must be between zero and one")
        stable_fingerprint(self.retained_output)


@dataclass(frozen=True, slots=True)
class Recommendation:
    decision_id: str
    decision_revision: int
    status: DecisionStatus
    packet_digest: str
    candidate_set_digest: str
    selected_candidate_id: str = ""
    selection_mode: str = ""
    explanation: str = ""
    evidence_ids: tuple[str, ...] = ()
    rejected_alternatives: tuple[str, ...] = ()
    model_calls: tuple[ModelCallIdentity, ...] = ()
    model_outputs: tuple[dict[str, Any], ...] = ()
    refusal: Refusal | None = None

    def __post_init__(self) -> None:
        required(self.decision_id, "decision_id")
        if self.decision_revision <= 0:
            raise ContractError("decision_revision must be positive")
        digest(self.packet_digest, "packet_digest")
        digest(self.candidate_set_digest, "candidate_set_digest")
        if self.status is DecisionStatus.REFUSED and self.refusal is None:
            raise ContractError("refused recommendation requires a refusal")
        if self.refusal is None and not self.selected_candidate_id:
            raise ContractError("successful recommendation requires a selected candidate")

    def as_dict(self) -> dict[str, Any]:
        refusal = None
        if self.refusal is not None:
            refusal = {
                "code": self.refusal.code.value,
                "reason": self.refusal.reason,
                "missing_premise": self.refusal.missing_premise,
            }
        return {
            "decision_id": self.decision_id,
            "decision_revision": self.decision_revision,
            "status": self.status.value,
            "packet_digest": self.packet_digest,
            "candidate_set_digest": self.candidate_set_digest,
            "selected_candidate_id": self.selected_candidate_id,
            "selection_mode": self.selection_mode,
            "explanation": self.explanation,
            "evidence_ids": list(self.evidence_ids),
            "rejected_alternatives": list(self.rejected_alternatives),
            "model_calls": [asdict(call) for call in self.model_calls],
            "model_outputs": [dict(output) for output in self.model_outputs],
            "refusal": refusal,
        }

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())
