"""Pure compatibility mappings for MultiAgentCommunication's WLG decision units.

This module deliberately imports no WLG runtime code. The consuming adapter supplies the
committed WLG data shapes and continues to own graph access, task claims, static gates,
mutation lowering, transactions, and receipts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, EffectTemplate, EntailmentProof, Recommendation
from aeos_kernel.errors import ContractError, RefusalCode
from aeos_kernel.evidence import (
    AuthorityPolicy,
    DecisionPacket,
    DecisionSubject,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
)

ADAPTER_ID = "multiagent.wlg"
ADAPTER_VERSION = "3"


@dataclass(frozen=True, slots=True)
class WlgEvidence:
    evidence_id: str
    source_tier: str
    project_id: str
    graph_revision: int
    payload: Mapping[str, Any]
    source_ref: str
    research_receipt_digest: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.evidence_id, "evidence_id"),
            (self.source_tier, "source_tier"),
            (self.project_id, "project_id"),
            (self.source_ref, "source_ref"),
        ):
            required(value, name)
        if type(self.graph_revision) is not int or self.graph_revision <= 0:
            raise ContractError("graph_revision must be positive")
        if self.research_receipt_digest:
            digest(self.research_receipt_digest, "research_receipt_digest")
        object.__setattr__(
            self,
            "payload",
            immutable_json_object(self.payload, "WLG evidence payload"),
        )


@dataclass(frozen=True, slots=True)
class WlgCandidate:
    candidate_id: str
    action: str
    title: str
    rationale: str
    source_tier: str
    cited_evidence_ids: tuple[str, ...]
    claimed_entailed: bool
    repair_plan: Mapping[str, Any]
    static_gate_passed: bool
    repair_contract_digest: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.candidate_id, "candidate_id"),
            (self.action, "action"),
            (self.title, "title"),
            (self.rationale, "rationale"),
            (self.source_tier, "source_tier"),
        ):
            required(value, name)
        if (
            type(self.cited_evidence_ids) is not tuple
            or not self.cited_evidence_ids
            or len(set(self.cited_evidence_ids)) != len(self.cited_evidence_ids)
        ):
            raise ContractError("WLG candidate citations must be nonempty and unique")
        if type(self.claimed_entailed) is not bool or type(self.static_gate_passed) is not bool:
            raise ContractError("WLG candidate controls must be booleans")
        digest(self.repair_contract_digest, "repair_contract_digest")
        object.__setattr__(
            self,
            "repair_plan",
            immutable_json_object(self.repair_plan, "WLG repair plan"),
        )


def build_wlg_packet(
    *,
    project_id: str,
    unit_id: str,
    graph_revision: int,
    finding: str,
    unit_digest: str,
    evidence: Sequence[WlgEvidence],
    canon_bundle_digest: str,
    source_head_pins: Mapping[str, str],
    allowed_actions: tuple[str, ...],
    policy: AuthorityPolicy,
    created_at: datetime,
) -> DecisionPacket:
    revision = str(graph_revision)
    subject = DecisionSubject(
        vertical_id="multiagent",
        tenant_id=project_id,
        subject_id=unit_id,
        subject_kind="wlg_decision_unit",
        revision=revision,
        content_digest=unit_digest,
        attributes={"finding": finding},
        source_refs=(
            SourceRef(
                source_type="wlg_graph_unit",
                source_id=unit_id,
                revision=revision,
                digest=unit_digest,
            ),
        ),
        allowed_uses=("decision", "model") if policy.permits_model_choice else ("decision",),
    )
    items = tuple(
        build_evidence_item(
            evidence_id=item.evidence_id,
            source_tier=item.source_tier,
            vertical_id=subject.vertical_id,
            tenant_id=item.project_id,
            subject_id=subject.subject_id,
            subject_revision=str(item.graph_revision),
            payload=dict(item.payload),
            source_ref=SourceRef(
                source_type="wlg_evidence",
                source_id=item.source_ref,
                revision=str(item.graph_revision),
                digest=stable_fingerprint(dict(item.payload)),
            ),
            observed_at=created_at,
            research_receipt_digest=item.research_receipt_digest,
            allowed_uses=("decision", "model") if policy.permits_model_choice else ("decision",),
        )
        for item in evidence
    )
    return build_decision_packet(
        packet_id="wlg_packet_"
        + stable_fingerprint(
            {"project_id": project_id, "unit_id": unit_id, "graph_revision": graph_revision}
        )[:24],
        subject=subject,
        evidence=items,
        authority_bundle_digest=canon_bundle_digest,
        policy=policy,
        allowed_actions=allowed_actions,
        source_head_pins=dict(source_head_pins),
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        created_at=created_at,
    )


def map_wlg_candidate(candidate: WlgCandidate) -> Candidate:
    """Map only a candidate already admitted by WLG's real candidate-bound static gate."""

    if candidate.static_gate_passed is not True:
        raise ContractError("WLG candidate has not passed the host static gate")
    digest(candidate.repair_contract_digest, "repair_contract_digest")
    return Candidate(
        candidate_id=candidate.candidate_id,
        action=candidate.action,
        title=candidate.title,
        explanation=candidate.rationale,
        expected_benefit="The registered graph requirement is satisfied without widening scope.",
        proof=EntailmentProof(
            source_tier=candidate.source_tier,
            cited_evidence_ids=candidate.cited_evidence_ids,
            reason=candidate.rationale,
            claimed_entailed=candidate.claimed_entailed,
        ),
        effect=EffectTemplate(
            operation="multiagent.wlg.apply_repair_plan",
            operation_version="1",
            parameters={
                "repair_plan": dict(candidate.repair_plan),
                "static_gate_receipt": {
                    "passed": True,
                    "repair_contract_digest": candidate.repair_contract_digest,
                },
            },
            boundary_tags=("wlg_graph_mutation",),
            expected_postcondition="registered_validator_postcondition",
            reversible=True,
            compensation_ref="wlg_receipt_bound_retraction",
        ),
    )


def to_wlg_decision_record(
    recommendation: Recommendation, *, packet: DecisionPacket, candidate: Candidate | None
) -> dict[str, Any]:
    """Return the source decision-record vocabulary without claiming a graph commit."""

    refusal = recommendation.refusal
    if refusal is None:
        if candidate is None or candidate.candidate_id != recommendation.selected_candidate_id:
            raise ContractError("WLG projection requires the exact selected candidate")
        selected = candidate
    else:
        if candidate is not None:
            raise ContractError("a refused WLG projection cannot carry a selected candidate")
        selected = None
    typed_op_plan = None
    if selected is not None and selected.effect is not None:
        typed_op_plan = selected.effect.parameters
    escalation = "no"
    if refusal is not None:
        if refusal.code in {RefusalCode.AUTHORITY_CONFLICT, RefusalCode.AMBIGUOUS_ENTAILMENT}:
            escalation = "A"
        elif refusal.code in {RefusalCode.INVALID_PACKET, RefusalCode.AUTHORITY_MISSING} or (
            refusal.code is RefusalCode.STALE_INPUT
            and refusal.reason
            in {
                "source-head pins are stale or unknown",
                "subject revision is not current",
            }
        ):
            escalation = "authority_failure"
        else:
            escalation = "B"
    expects_decision_receipt = escalation != "authority_failure"
    receipt_expectation = {
        "required": expects_decision_receipt,
        "kind": (
            "effect_commit"
            if selected is not None
            else ("decision_only" if expects_decision_receipt else "none")
        ),
        "status": (
            "pending_host_execution"
            if selected is not None
            else ("pending_host_persistence" if expects_decision_receipt else "no_effect")
        ),
    }
    return {
        "project_id": packet.subject.tenant_id,
        "unit_id": packet.subject.subject_id,
        "finding": str(packet.subject.attributes.get("finding", "")),
        "decision": selected.action if selected is not None else "escalation",
        "canon_basis": recommendation.explanation,
        "graph_requirements_evidence": [
            {"evidence_id": evidence_id}
            for evidence_id in (
                recommendation.evidence_ids
                if selected is not None
                else tuple(item.evidence_id for item in packet.evidence)
            )
        ],
        "analysis_performed": [recommendation.selection_mode],
        "alternatives_rejected": [
            {"candidate_id": candidate_id} for candidate_id in recommendation.rejected_alternatives
        ],
        "typed_op_plan": typed_op_plan,
        "lint_disposition": "pending_host_regate" if selected is not None else "no_effect",
        "residual_risk": "host commit and postcondition remain unverified",
        "needs_operator": escalation,
        "escalation_premise": "" if refusal is None else refusal.missing_premise or refusal.reason,
        "selection_mode": recommendation.selection_mode or "escalation",
        "audit": {
            "aeos_recommendation_digest": recommendation.digest,
            "expected_receipt": receipt_expectation,
        },
    }
