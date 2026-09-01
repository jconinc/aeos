from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from aeos_kernel import DecisionEngine, DecisionStatus, RefusalCode
from tests.factories import (
    NOW,
    AcceptingVerifier,
    FixedClock,
    ScriptedModel,
    candidate,
    evidence,
    packet,
    policy,
)


def engine(
    verifier: AcceptingVerifier | None = None, model: ScriptedModel | None = None
) -> DecisionEngine:
    return DecisionEngine(
        verifier=verifier or AcceptingVerifier(), clock=FixedClock(), model_gateway=model
    )


def test_unique_validated_entailment_selects_without_model() -> None:
    result = engine().decide(packet(), (candidate(),))
    assert result.status is DecisionStatus.PROPOSED
    assert result.selected_candidate_id == "candidate-1"
    assert result.selection_mode == "auto_entailed"
    assert result.model_calls == ()


def test_cardinality_is_not_entailment() -> None:
    result = engine().decide(packet(), (candidate(entailed=False),))
    assert result.status is DecisionStatus.REFUSED
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MODEL_REQUIRED


def test_fabricated_citation_is_ineligible() -> None:
    result = engine().decide(packet(), (candidate(evidence_ids=("invented",)),))
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.NO_ELIGIBLE_CANDIDATE


def test_cross_tenant_evidence_fails_before_candidate_selection() -> None:
    bad = evidence(tenant_id="someone-else")
    result = engine().decide(packet(items=(bad,)), (candidate(),))
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.CROSS_SCOPE_EVIDENCE


def test_stale_live_subject_revision_fails_closed() -> None:
    result = engine(AcceptingVerifier(revision="2")).decide(packet(), (candidate(),))
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.STALE_INPUT


def test_expired_evidence_uses_current_clock_not_packet_creation_time() -> None:
    expiring = evidence(expires_at=NOW + timedelta(minutes=1))
    decision_engine = DecisionEngine(
        verifier=AcceptingVerifier(),
        clock=FixedClock(NOW + timedelta(minutes=2)),
    )
    result = decision_engine.decide(packet(items=(expiring,)), (candidate(),))
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.STALE_INPUT


def test_tampered_packet_digest_fails_closed() -> None:
    bad = replace(packet(), packet_digest="f" * 64)
    result = engine().decide(bad, (candidate(),))
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.INVALID_PACKET


def test_unauthorized_effect_boundary_makes_candidate_ineligible() -> None:
    result = engine().decide(packet(), (candidate(boundary_tags=("publish",)),))
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.NO_ELIGIBLE_CANDIDATE


def test_model_selects_only_after_reverse_order_consensus_and_retains_outputs() -> None:
    scripted = ScriptedModel(["candidate-1", "candidate-1"])
    candidates = (
        candidate("candidate-1", entailed=False),
        candidate("candidate-2", action="improve_description", entailed=False),
    )
    result = engine(model=scripted).decide(packet(authority_policy=policy(model=True)), candidates)
    assert result.selected_candidate_id == "candidate-1"
    assert result.selection_mode == "model_eligible"
    assert [request.candidate_order for request in scripted.requests] == [
        ("candidate-1", "candidate-2"),
        ("candidate-2", "candidate-1"),
    ]
    assert len(result.model_calls) == 2
    assert len(result.model_outputs) == 2


def test_model_order_disagreement_fails_closed() -> None:
    scripted = ScriptedModel(["candidate-1", "candidate-2"])
    candidates = (
        candidate("candidate-1", entailed=False),
        candidate("candidate-2", action="improve_description", entailed=False),
    )
    result = engine(model=scripted).decide(packet(authority_policy=policy(model=True)), candidates)
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MODEL_DISAGREEMENT


def test_model_cannot_invent_candidate() -> None:
    scripted = ScriptedModel(["invented"])
    result = engine(model=scripted).decide(
        packet(authority_policy=policy(model=True)), (candidate(entailed=False),)
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MODEL_INVALID


def test_multiple_validated_entailments_fail_closed_without_model() -> None:
    candidates = (
        candidate("candidate-1"),
        candidate("candidate-2", action="improve_description"),
    )
    result = engine().decide(packet(), candidates)
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.AMBIGUOUS_ENTAILMENT
