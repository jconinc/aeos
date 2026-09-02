"""Candidate, effect-template, model-call, and recommendation contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, thaw_json
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
        if len(set(self.cited_evidence_ids)) != len(self.cited_evidence_ids):
            raise ContractError("entailment proof citations must be unique")


@dataclass(frozen=True, slots=True)
class EffectTemplate:
    operation: str
    operation_version: str
    parameters: dict[str, Any]
    boundary_tags: tuple[str, ...]
    expected_postcondition: str
    reversible: bool
    compensation_ref: str = ""
    cost_ceiling_minor_units: int = 0
    fanout_ceiling: int = 1

    def __post_init__(self) -> None:
        required(self.operation, "operation")
        required(self.operation_version, "operation_version")
        required(self.expected_postcondition, "expected_postcondition")
        if self.cost_ceiling_minor_units < 0:
            raise ContractError("effect cost ceiling must be nonnegative")
        if self.fanout_ceiling <= 0:
            raise ContractError("effect fanout ceiling must be positive")
        if len(set(self.boundary_tags)) != len(self.boundary_tags):
            raise ContractError("effect boundary tags must be unique")
        for tag in self.boundary_tags:
            required(tag, "effect boundary tag")
        object.__setattr__(
            self,
            "parameters",
            immutable_json_object(self.parameters, "effect parameters"),
        )


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
        required(self.expected_benefit, "expected_benefit")

    def as_dict(self) -> dict[str, Any]:
        effect = None
        if self.effect is not None:
            effect = {
                "operation": self.effect.operation,
                "operation_version": self.effect.operation_version,
                "parameters": thaw_json(self.effect.parameters),
                "boundary_tags": list(self.effect.boundary_tags),
                "expected_postcondition": self.effect.expected_postcondition,
                "reversible": self.effect.reversible,
                "compensation_ref": self.effect.compensation_ref,
                "cost_ceiling_minor_units": self.effect.cost_ceiling_minor_units,
                "fanout_ceiling": self.effect.fanout_ceiling,
            }
        return {
            "candidate_id": self.candidate_id,
            "action": self.action,
            "title": self.title,
            "explanation": self.explanation,
            "expected_benefit": self.expected_benefit,
            "uncertainty": self.uncertainty,
            "proof": {
                "source_tier": self.proof.source_tier,
                "cited_evidence_ids": list(self.proof.cited_evidence_ids),
                "reason": self.proof.reason,
                "claimed_entailed": self.proof.claimed_entailed,
            },
            "effect": effect,
        }


def candidate_set_digest(candidates: tuple[Candidate, ...]) -> str:
    return stable_fingerprint([candidate.as_dict() for candidate in candidates])


@dataclass(frozen=True, slots=True)
class ModelCallIdentity:
    provider: str
    model_id: str
    prompt_digest: str
    generation_parameters_digest: str
    context_classification: str
    attempt: int
    cost_minor_units: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        required(self.provider, "provider")
        required(self.model_id, "model_id")
        required(self.context_classification, "context_classification")
        digest(self.prompt_digest, "prompt_digest")
        digest(self.generation_parameters_digest, "generation_parameters_digest")
        if (
            self.attempt <= 0
            or self.cost_minor_units < 0
            or self.input_tokens < 0
            or self.output_tokens < 0
        ):
            raise ContractError("model attempt must be positive and usage nonnegative")


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
        if len(set(self.citations)) != len(self.citations):
            raise ContractError("model citations must be unique")
        if not 0 <= self.confidence <= 1:
            raise ContractError("model confidence must be between zero and one")
        object.__setattr__(
            self,
            "retained_output",
            immutable_json_object(self.retained_output, "model retained_output"),
        )


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
        if self.refusal is not None and self.selected_candidate_id:
            raise ContractError("refused recommendation cannot select a candidate")
        if len(self.model_calls) != len(self.model_outputs):
            raise ContractError("each model call requires one retained structured output")
        object.__setattr__(
            self,
            "model_outputs",
            tuple(
                immutable_json_object(output, "recommendation model output")
                for output in self.model_outputs
            ),
        )

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
            "model_outputs": [thaw_json(output) for output in self.model_outputs],
            "refusal": refusal,
        }

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())
