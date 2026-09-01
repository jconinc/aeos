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

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, EffectTemplate, EntailmentProof, Recommendation
from aeos_kernel.evidence import (
    AuthorityPolicy,
    DecisionPacket,
    DecisionSubject,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
)

ADAPTER_ID = "multiagent.wlg"
ADAPTER_VERSION = "1"


@dataclass(frozen=True, slots=True)
class WlgEvidence:
    evidence_id: str
    source_tier: str
    payload: Mapping[str, Any]
    source_ref: str
    research_receipt_digest: str = ""


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
    )
    items = tuple(
        build_evidence_item(
            evidence_id=item.evidence_id,
            source_tier=item.source_tier,
            vertical_id=subject.vertical_id,
            tenant_id=subject.tenant_id,
            subject_id=subject.subject_id,
            subject_revision=subject.revision,
            payload=dict(item.payload),
            source_ref=SourceRef(
                source_type="wlg_evidence",
                source_id=item.source_ref,
                revision=revision,
                digest=stable_fingerprint(dict(item.payload)),
            ),
            observed_at=created_at,
            research_receipt_digest=item.research_receipt_digest,
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
    return Candidate(
        candidate_id=candidate.candidate_id,
        action=candidate.action,
        title=candidate.title,
        explanation=candidate.rationale,
        proof=EntailmentProof(
            source_tier=candidate.source_tier,
            cited_evidence_ids=candidate.cited_evidence_ids,
            reason=candidate.rationale,
            claimed_entailed=candidate.claimed_entailed,
        ),
        effect=EffectTemplate(
            operation="multiagent.wlg.apply_repair_plan",
            parameters={"repair_plan": dict(candidate.repair_plan)},
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
    typed_op_plan = None
    if candidate is not None and candidate.effect is not None:
        typed_op_plan = candidate.effect.parameters
    return {
        "project_id": packet.subject.tenant_id,
        "unit_id": packet.subject.subject_id,
        "finding": str(packet.subject.attributes.get("finding", "")),
        "decision": candidate.action if candidate is not None else "escalation",
        "canon_basis": recommendation.explanation,
        "graph_requirements_evidence": [
            {"evidence_id": evidence_id} for evidence_id in recommendation.evidence_ids
        ],
        "analysis_performed": [recommendation.selection_mode],
        "alternatives_rejected": [
            {"candidate_id": candidate_id} for candidate_id in recommendation.rejected_alternatives
        ],
        "typed_op_plan": typed_op_plan,
        "lint_disposition": "pending_host_static_gate" if candidate is not None else "no_effect",
        "residual_risk": "host commit and postcondition remain unverified",
        "needs_operator": "B" if refusal is not None else "no",
        "escalation_premise": "" if refusal is None else refusal.missing_premise or refusal.reason,
        "selection_mode": recommendation.selection_mode or "escalation",
        "audit": {"aeos_recommendation_digest": recommendation.digest},
    }
