"""Candidate, effect-template, model-call, and recommendation contracts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, thaw_json
from aeos_kernel.canonical import canonical_json, stable_fingerprint
from aeos_kernel.errors import MODEL_ESCALATIONS, ContractError, Refusal, RefusalCode
from aeos_kernel.vocabulary import DecisionStatus

_PREMISE_REF = re.compile(r"(?:fact|rule|area):[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")


def _validate_premise_refs(refs: object, container_type: type) -> None:
    if not isinstance(refs, container_type) or not isinstance(refs, (tuple, list)):
        raise ContractError("premise_refs must contain typed premise identifiers")
    if any(not isinstance(ref, str) or _PREMISE_REF.fullmatch(ref) is None for ref in refs):
        raise ContractError("premise_refs must contain typed premise identifiers")
    if len(set(refs)) != len(refs):
        raise ContractError("premise_refs must be unique")


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
    principle_ids: tuple[str, ...] = ()
    escalation: RefusalCode | None = None
    missing_premise: str = ""
    premise_refs: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.premise_refs is not None:
            _validate_premise_refs(self.premise_refs, tuple)
        if self.escalation is None:
            required(self.candidate_id, "candidate_id")
            if self.missing_premise:
                raise ContractError("only an escalation names a missing premise")
        else:
            if self.escalation not in MODEL_ESCALATIONS:
                raise ContractError("a model may escalate only a missing principle or fact")
            if self.candidate_id:
                raise ContractError("an escalation cannot select a candidate")
            required(self.missing_premise, "missing_premise")
        required(self.rationale, "rationale")
        if self.escalation is None and not self.citations:
            raise ContractError("model decision must cite evidence")
        if len(set(self.citations)) != len(self.citations):
            raise ContractError("model citations must be unique")
        if len(set(self.principle_ids)) != len(self.principle_ids):
            raise ContractError("model principle_ids must be unique")
        if not 0 <= self.confidence <= 1:
            raise ContractError("model confidence must be between zero and one")
        object.__setattr__(
            self,
            "retained_output",
            immutable_json_object(self.retained_output, "model retained_output"),
        )


@dataclass(frozen=True, slots=True)
class ModelReviewIssue:
    code: str
    principle_id: str
    fact_refs: tuple[str, ...]
    candidate_id: str
    explanation: str


@dataclass(frozen=True, slots=True)
class ModelReview:
    verdict: str
    issues: tuple[ModelReviewIssue, ...]
    missing_premise: str | None
    identity: ModelCallIdentity
    retained_output: dict[str, Any]
    premise_refs: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.premise_refs is not None:
            _validate_premise_refs(self.premise_refs, tuple)
        object.__setattr__(
            self,
            "retained_output",
            immutable_json_object(self.retained_output, "model review retained_output"),
        )


@dataclass(frozen=True, slots=True)
class ExpandedModelChoice:
    """Host-validated expansion of one retained chooser answer, never model authority."""

    attempt: int
    contract_version: str
    prompt_digest: str
    key_map_digest: str
    expansion_input_digest: str
    expanded_choice: dict[str, Any]
    canonical_expanded_json: str
    semantic_payload: dict[str, Any]
    semantic_fingerprint: str
    full_digest: str

    def __post_init__(self) -> None:
        if self.attempt <= 0:
            raise ContractError("expanded choice attempt must be positive")
        required(self.contract_version, "expansion contract_version")
        for name in (
            "prompt_digest",
            "key_map_digest",
            "expansion_input_digest",
            "semantic_fingerprint",
            "full_digest",
        ):
            digest(getattr(self, name), name)
        for name in ("expanded_choice", "semantic_payload"):
            object.__setattr__(self, name, immutable_json_object(getattr(self, name), name))
        if canonical_json(self.expanded_choice) != self.canonical_expanded_json:
            raise ContractError("expanded choice bytes differ from its retained object")
        if stable_fingerprint(self.semantic_payload) != self.semantic_fingerprint:
            raise ContractError("expanded choice semantic fingerprint differs from its payload")

    def as_dict(self) -> dict[str, Any]:
        return {field.name: thaw_json(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class ModelChoiceFieldDiff:
    path: str
    proposed_present: bool
    proposed_value: Any
    corroborating_present: bool
    corroborating_value: Any

    def __post_init__(self) -> None:
        required(self.path, "choice diff path")
        for side in ("proposed", "corroborating"):
            present = getattr(self, f"{side}_present")
            value = getattr(self, f"{side}_value")
            if not isinstance(present, bool) or (not present and value is not None):
                raise ContractError("choice diff presence must agree with its value")
            frozen = immutable_json_object({"value": value}, "choice diff value")["value"]
            object.__setattr__(self, f"{side}_value", frozen)

    def as_dict(self) -> dict[str, Any]:
        return {field.name: thaw_json(getattr(self, field.name)) for field in fields(self)}


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
    model_protocol_version: str = ""
    model_call_purposes: tuple[str, ...] = ()
    model_request_digests: tuple[str, ...] = ()
    model_choice_expansions: tuple[ExpandedModelChoice, ...] = ()

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
        if self.model_protocol_version:
            if (
                self.model_protocol_version
                not in {"aeos.reviewed-choice@1", "aeos.reviewed-choice@2"}
                or len(self.model_calls) != len(self.model_call_purposes)
                or len(self.model_calls) != len(self.model_request_digests)
                or any(p not in {"choose", "review"} for p in self.model_call_purposes)
            ):
                raise ContractError("invalid reviewed model evidence")
            for value in self.model_request_digests:
                digest(value, "model_request_digest")
        elif self.model_call_purposes or self.model_request_digests:
            raise ContractError("model evidence requires a protocol version")
        if self.model_choice_expansions:
            if self.model_protocol_version != "aeos.reviewed-choice@2":
                raise ContractError("expanded choices require reviewed-choice version 2")
            chooser_calls = {
                (attempt, request_digest)
                for attempt, (call, purpose, request_digest) in enumerate(
                    zip(
                        self.model_calls,
                        self.model_call_purposes,
                        self.model_request_digests,
                        strict=True,
                    ),
                    1,
                )
                if purpose == "choose"
                and call.attempt == attempt
                and call.prompt_digest == request_digest
            }
            attempts = [item.attempt for item in self.model_choice_expansions]
            if attempts != sorted(set(attempts)):
                raise ContractError("expanded choices must follow unique chooser attempts")
            for item in self.model_choice_expansions:
                if (item.attempt, item.prompt_digest) not in chooser_calls:
                    raise ContractError("expanded choice does not bind its retained chooser call")
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
        value = {
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
        if self.model_protocol_version:
            value.update(
                {
                    "model_protocol_version": self.model_protocol_version,
                    "model_call_purposes": list(self.model_call_purposes),
                    "model_request_digests": list(self.model_request_digests),
                }
            )
        if self.model_choice_expansions:
            value["model_choice_expansions"] = [
                item.as_dict() for item in self.model_choice_expansions
            ]
        return value

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())
