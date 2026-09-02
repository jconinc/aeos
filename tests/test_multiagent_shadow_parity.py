from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from aeos_kernel import (
    AuthorityLevel,
    AuthorityPolicy,
    DecisionEngine,
    DecisionIntensity,
    DecisionStatus,
    ModelCallIdentity,
    ModelDecision,
    RefusalCode,
)
from aeos_kernel.adapters.multiagent import (
    ADAPTER_VERSION,
    WlgCandidate,
    WlgEvidence,
    build_wlg_packet,
    map_wlg_candidate,
    to_wlg_decision_record,
)
from aeos_kernel.ports import ModelChoiceRequest
from tests.factories import NOW, FixedClock
from tests.test_multiagent_source_compatibility import PINNED_HEAD, require_pinned_source

PARITY_MANIFEST = Path(__file__).parents[1] / "docs" / "multiagent-shadow-parity-v2.json"

pytestmark = pytest.mark.compatibility


class ParityVerifier:
    def __init__(self, *, heads_valid: bool = True, revision: str | None = None) -> None:
        self.heads_valid = heads_valid
        self.revision = revision

    def verify_authority_bundle(self, digest: str) -> bool:
        return digest == "c" * 64

    def verify_source_heads(self, source_head_pins: dict[str, str]) -> bool:
        return self.heads_valid and bool(source_head_pins)

    def current_subject_revision(self, subject: Any) -> str:
        return self.revision or str(subject.revision)

    def verify_research_receipt(self, evidence: Any) -> bool:
        return bool(evidence.research_receipt_digest)


class SequenceModel:
    def __init__(
        self,
        selected_ids: tuple[str, ...],
        *,
        citations: dict[str, tuple[str, ...]],
        confidence: float = 0.9,
    ) -> None:
        self.selected_ids = selected_ids
        self.citations = citations
        self.confidence = confidence
        self.requests: list[ModelChoiceRequest] = []

    def choose(self, request: ModelChoiceRequest) -> ModelDecision:
        self.requests.append(request)
        selected_id = self.selected_ids[len(self.requests) - 1]
        citations = self.citations[selected_id]
        return ModelDecision(
            candidate_id=selected_id,
            rationale="The exact cited evidence governs this bounded candidate.",
            citations=citations,
            confidence=self.confidence,
            identity=ModelCallIdentity(
                provider=request.provider,
                model_id=request.model_id,
                prompt_digest=request.prompt_digest,
                generation_parameters_digest=request.generation_parameters_digest,
                context_classification=request.context_classification,
                attempt=request.attempt,
                cost_minor_units=1,
                input_tokens=20,
                output_tokens=8,
            ),
            retained_output={"candidate_id": selected_id, "citations": list(citations)},
        )


def source_fixtures():  # type: ignore[no-untyped-def]
    require_pinned_source()
    from claude_coord.tests import test_canon_decision

    return test_canon_decision


def policy(*, model: bool = False) -> AuthorityPolicy:
    from aeos_kernel import stable_fingerprint

    return AuthorityPolicy(
        policy_id="multiagent-canon-decision",
        policy_version="3",
        level=AuthorityLevel.AGENT_JUDGMENT if model else AuthorityLevel.DETERMINISTIC,
        intensity=DecisionIntensity.INTERNAL_EFFECT,
        allowed_boundary_tags=("wlg_graph_mutation",),
        permits_model_choice=model,
        max_model_calls=2 if model else 0,
        max_model_cost_minor_units=5 if model else 0,
        model_provider="configured-reasoner" if model else "",
        model_id="reasoner-v1" if model else "",
        model_context_classification="internal-safe" if model else "",
        model_generation_parameters_digest=stable_fingerprint({"temperature": 0}) if model else "",
    )


def map_packet(source_packet: Any, *, model: bool = False):  # type: ignore[no-untyped-def]
    return build_wlg_packet(
        project_id=source_packet.project_id,
        unit_id=source_packet.unit_id,
        graph_revision=source_packet.graph_revision,
        finding=source_packet.finding,
        unit_digest="a" * 64,
        evidence=tuple(
            WlgEvidence(
                evidence_id=item.evidence_id,
                source_tier=item.source_tier,
                project_id=item.project_id,
                graph_revision=item.graph_revision,
                payload=dict(item.payload),
                source_ref=item.evidence_id,
            )
            for item in source_packet.evidence
        ),
        canon_bundle_digest="c" * 64,
        source_head_pins=dict(source_packet.source_head_pins),
        allowed_actions=tuple(source_packet.allowed_actions),
        policy=policy(model=model),
        created_at=NOW,
    )


def gated_source_packet(
    source: Any,
    source_packet: Any,
    source_candidates: tuple[Any, ...],
    *,
    contract: dict[str, Any] | None = None,
) -> tuple[Any, str, tuple[bool, ...]]:
    from claude_coord.wlg.decision_engine.canon_decision import (
        _repair_contract_sha256,
        _static_gate_ok,
    )

    current_contract = contract or source._contract_for(source_packet, source_candidates)
    gated = dataclasses.replace(source_packet, repair_contract=current_contract)
    return (
        gated,
        _repair_contract_sha256(gated),
        tuple(_static_gate_ok(candidate, gated)[0] for candidate in source_candidates),
    )


def map_candidate(source_candidate: Any, *, gate_digest: str, gate_passed: bool = True):  # type: ignore[no-untyped-def]
    return map_wlg_candidate(
        WlgCandidate(
            candidate_id=source_candidate.cid,
            action=source_candidate.candidate.action,
            title=f"Apply {source_candidate.candidate.action}",
            rationale=source_candidate.proof.entailment_reason,
            source_tier=source_candidate.proof.source_tier,
            cited_evidence_ids=tuple(source_candidate.proof.cited_evidence_ids),
            claimed_entailed=source_candidate.proof.claimed_entailed,
            repair_plan={"ops": [dataclasses.asdict(op) for op in source_candidate.ops]},
            static_gate_passed=gate_passed,
            repair_contract_digest=gate_digest,
        )
    )


def project(new: Any, packet: Any, candidates: tuple[Any, ...]) -> dict[str, Any]:
    selected = None
    if new.refusal is None:
        selected = next(
            item for item in candidates if item.candidate_id == new.selected_candidate_id
        )
    return to_wlg_decision_record(new, packet=packet, candidate=selected)


def assert_projection_parity(old: Any, new: Any, record: dict[str, Any]) -> None:
    assert old.decision == record["decision"]
    assert old.needs_operator == record["needs_operator"]
    assert (old.typed_op_plan is not None) == (record["typed_op_plan"] is not None)
    old_citations = {item["id"] for item in old.graph_requirements_evidence}
    new_citations = {item["evidence_id"] for item in record["graph_requirements_evidence"]}
    assert old_citations == new_citations
    expected = record["audit"]["expected_receipt"]
    assert expected["kind"] == ("effect_commit" if old.typed_op_plan else "decision_only")
    if old.typed_op_plan is not None:
        source_ops = [
            (item.op_type, item.subject_id, item.field, item.edge_type, item.target_id)
            for item in old.typed_op_plan.ops
        ]
        mapped_ops = [
            (
                item["op_type"],
                item["subject_id"],
                item["field"],
                item["edge_type"],
                item["target_id"],
            )
            for item in record["typed_op_plan"]["repair_plan"]["ops"]
        ]
        assert source_ops == mapped_ops


def test_shadow_manifest_pins_actual_source_and_host_owned_fixture_contracts() -> None:
    manifest = json.loads(PARITY_MANIFEST.read_text(encoding="utf-8"))
    source_fixtures()
    assert manifest["source_commit"] == PINNED_HEAD
    assert manifest["aeos_adapter"] == f"multiagent.wlg@{ADAPTER_VERSION}"
    assert manifest["effect_policy"] == "read_only_shadow_no_effect_execution"
    assert set(manifest["comparison_fields"]) == {
        "selected_decision_or_refusal",
        "citations",
        "escalation_class",
        "typed_effect",
        "expected_receipt",
    }
    from claude_coord.tests import test_canon_decision_pipeline as pipeline
    from claude_coord.tests import test_intent_authority_lift_canon_decision as authority_lift

    for fixture in manifest["host_owned_contract_fixtures"]:
        module = pipeline if fixture["source_fixture"].endswith("pipeline.py") else authority_lift
        assert callable(getattr(module, fixture["source_test"]))


def test_pinned_entailed_fixture_has_full_projection_parity() -> None:
    source = source_fixtures()
    source_packet = source._packet()
    source_candidate = source._cand("link_target", "t1", ["e1"])
    old = source._run(source_packet, [source_candidate], model_call=source._no_model)
    _gated, gate_digest, gate_results = gated_source_packet(
        source, source_packet, (source_candidate,)
    )
    assert gate_results == (True,)
    packet = map_packet(source_packet)
    candidate = map_candidate(source_candidate, gate_digest=gate_digest)
    new = DecisionEngine(verifier=ParityVerifier(), clock=FixedClock()).decide(packet, (candidate,))
    record = project(new, packet, (candidate,))
    assert old.audit["selected_candidate_id"] == new.selected_candidate_id
    assert old.selection_mode == new.selection_mode == "auto_entailed"
    assert record["typed_op_plan"]["static_gate_receipt"]["repair_contract_digest"] == gate_digest
    assert_projection_parity(old, new, record)


def test_pinned_authority_precedence_and_conflict_have_exact_escalation_parity() -> None:
    source = source_fixtures()
    source_packet = source._packet(
        evs=[source._ev("e1", tier="requirement"), source._ev("e2", tier="graph")]
    )
    high = source._cand("link_target", "t1", ["e1"], tier="requirement")
    low = source._cand("link_target", "t2", ["e2"], tier="graph")
    old = source._run(source_packet, [high, low], model_call=source._no_model)
    _gated, gate_digest, gate_results = gated_source_packet(source, source_packet, (high, low))
    assert gate_results == (True, True)
    packet = map_packet(source_packet)
    candidates = tuple(map_candidate(item, gate_digest=gate_digest) for item in (high, low))
    new = DecisionEngine(verifier=ParityVerifier(), clock=FixedClock()).decide(packet, candidates)
    assert old.audit["selected_candidate_id"] == new.selected_candidate_id
    assert_projection_parity(old, new, project(new, packet, candidates))

    conflict_packet = source._packet(
        evs=[source._ev("e1", tier="requirement"), source._ev("e2", tier="requirement")]
    )
    first = source._cand("link_target", "t1", ["e1"], tier="requirement")
    second = source._cand("link_target", "t2", ["e2"], tier="requirement")
    old_conflict = source._run(conflict_packet, [first, second], model_call=source._no_model)
    _gated, gate_digest, _results = gated_source_packet(source, conflict_packet, (first, second))
    packet = map_packet(conflict_packet)
    candidates = tuple(map_candidate(item, gate_digest=gate_digest) for item in (first, second))
    new_conflict = DecisionEngine(verifier=ParityVerifier(), clock=FixedClock()).decide(
        packet, candidates
    )
    assert new_conflict.refusal is not None
    assert new_conflict.refusal.code is RefusalCode.AMBIGUOUS_ENTAILMENT
    assert_projection_parity(old_conflict, new_conflict, project(new_conflict, packet, candidates))


@pytest.mark.parametrize("plant", ["fabricated_citation", "invented_candidate", "low_confidence"])
def test_pinned_model_red_plants_refuse_without_effect(plant: str) -> None:
    source = source_fixtures()
    source_packet = source._packet()
    source_candidate = source._cand("link_target", "t1", ["e1"], entailed=False)
    selected_id = source_candidate.cid
    citations = ("ghost",) if plant == "fabricated_citation" else ("e1",)
    chosen_id = "INVENTED" if plant == "invented_candidate" else selected_id
    confidence = 0.4 if plant == "low_confidence" else 0.9
    old = source._run(
        source_packet,
        [source_candidate],
        model_call=lambda _system, _prompt: source._pick(
            chosen_id, citations=list(citations), confidence=confidence
        ),
    )
    _gated, gate_digest, gate_results = gated_source_packet(
        source, source_packet, (source_candidate,)
    )
    assert gate_results == (True,)
    packet = map_packet(source_packet, model=True)
    candidate = map_candidate(source_candidate, gate_digest=gate_digest)
    model = SequenceModel((chosen_id,), citations={chosen_id: citations}, confidence=confidence)
    new = DecisionEngine(
        verifier=ParityVerifier(),
        clock=FixedClock(),
        model_gateway=model,
        minimum_model_confidence=0.70,
    ).decide(packet, (candidate,))
    assert new.status is DecisionStatus.REFUSED
    assert new.refusal is not None and new.refusal.code is RefusalCode.MODEL_INVALID
    assert_projection_parity(old, new, project(new, packet, (candidate,)))


def test_pinned_reverse_order_model_acceptance_and_disagreement_have_parity() -> None:
    source = source_fixtures()
    source_packet = source._packet(evs=[source._ev("e1"), source._ev("e2")])
    first = source._cand("link_target", "t1", ["e1"], entailed=False)
    second = source._cand("link_target", "t2", ["e2"], entailed=False)
    _gated, gate_digest, gate_results = gated_source_packet(source, source_packet, (first, second))
    assert gate_results == (True, True)
    packet = map_packet(source_packet, model=True)
    candidates = tuple(map_candidate(item, gate_digest=gate_digest) for item in (first, second))

    calls = {"count": 0}

    def stable_choice(_system: str, _prompt: str) -> dict[str, Any]:
        calls["count"] += 1
        return source._with_model_identity(
            source._pick(second, citations=["e2"]),
            prompt_hash=str(calls["count"]) * 64,
            params_hash=str(calls["count"] + 2) * 64,
        )

    old = source._run(source_packet, [first, second], model_call=stable_choice)
    new = DecisionEngine(
        verifier=ParityVerifier(),
        clock=FixedClock(),
        model_gateway=SequenceModel((second.cid, second.cid), citations={second.cid: ("e2",)}),
        minimum_model_confidence=0.70,
    ).decide(packet, candidates)
    assert old.audit["selected_candidate_id"] == new.selected_candidate_id
    assert_projection_parity(old, new, project(new, packet, candidates))

    order_calls = {"count": 0}

    def order_biased(_system: str, prompt: str) -> dict[str, Any]:
        question = json.loads(prompt)
        choice = question["allowed_candidates"][0]
        citation = "e1" if choice["target_id"] == "t1" else "e2"
        order_calls["count"] += 1
        return source._with_model_identity(
            source._pick(choice["candidate_id"], citations=[citation]),
            prompt_hash=str(order_calls["count"]) * 64,
            params_hash=str(order_calls["count"] + 2) * 64,
        )

    old_disagreement = source._run(source_packet, [first, second], model_call=order_biased)
    new_disagreement = DecisionEngine(
        verifier=ParityVerifier(),
        clock=FixedClock(),
        model_gateway=SequenceModel(
            (first.cid, second.cid), citations={first.cid: ("e1",), second.cid: ("e2",)}
        ),
        minimum_model_confidence=0.70,
    ).decide(packet, candidates)
    assert new_disagreement.refusal is not None
    assert new_disagreement.refusal.code is RefusalCode.MODEL_DISAGREEMENT
    assert_projection_parity(
        old_disagreement,
        new_disagreement,
        project(new_disagreement, packet, candidates),
    )


@pytest.mark.parametrize("plant", ["cross_project", "stale_revision"])
def test_pinned_scope_and_staleness_red_plants_have_parity(plant: str) -> None:
    source = source_fixtures()
    evidence = (
        source._ev("e1", proj="OTHER") if plant == "cross_project" else source._ev("e1", rev=99)
    )
    source_packet = source._packet(evs=[evidence])
    source_candidate = source._cand("link_target", "t1", ["e1"])
    old = source._run(source_packet, [source_candidate], model_call=source._no_model)
    _gated, gate_digest, gate_results = gated_source_packet(
        source, source_packet, (source_candidate,)
    )
    assert gate_results == (True,)
    packet = map_packet(source_packet)
    candidate = map_candidate(source_candidate, gate_digest=gate_digest)
    new = DecisionEngine(verifier=ParityVerifier(), clock=FixedClock()).decide(packet, (candidate,))
    assert new.refusal is not None
    assert new.refusal.code is (
        RefusalCode.CROSS_SCOPE_EVIDENCE if plant == "cross_project" else RefusalCode.STALE_INPUT
    )
    assert_projection_parity(old, new, project(new, packet, (candidate,)))


def test_pinned_static_gate_rejection_cannot_enter_the_aeos_candidate_set() -> None:
    source = source_fixtures()
    source_packet = source._packet()
    admitted = source._cand("link_target", "t1", ["e1"])
    rejected = source._cand("link_target", "t2", ["e1"])
    contract = source._contract_for(source_packet, [admitted])
    old = source._run(
        source_packet,
        [rejected],
        model_call=source._no_model,
        contract=contract,
    )
    _gated, gate_digest, gate_results = gated_source_packet(
        source, source_packet, (rejected,), contract=contract
    )
    assert gate_results == (False,)
    with pytest.raises(ValueError, match="static gate"):
        map_candidate(rejected, gate_digest=gate_digest, gate_passed=False)
    packet = map_packet(source_packet)
    new = DecisionEngine(verifier=ParityVerifier(), clock=FixedClock()).decide(packet, ())
    assert new.refusal is not None and new.refusal.code is RefusalCode.NO_ELIGIBLE_CANDIDATE
    assert_projection_parity(old, new, project(new, packet, ()))


def test_pinned_source_head_drift_is_an_authority_failure_with_no_receipt() -> None:
    source = source_fixtures()
    source_packet = source._packet()
    source_candidate = source._cand("link_target", "t1", ["e1"])
    with pytest.raises(source.CanonAuthorityError):
        source.run_canon_decision(
            source_packet,
            [source_candidate],
            model_call=source._no_model,
            pins=source._pins(heads_ok=False),
        )
    _gated, gate_digest, _gate_results = gated_source_packet(
        source, source_packet, (source_candidate,)
    )
    packet = map_packet(source_packet)
    candidate = map_candidate(source_candidate, gate_digest=gate_digest)
    new = DecisionEngine(verifier=ParityVerifier(heads_valid=False), clock=FixedClock()).decide(
        packet, (candidate,)
    )
    record = project(new, packet, (candidate,))
    assert new.refusal is not None and new.refusal.code is RefusalCode.STALE_INPUT
    assert record["needs_operator"] == "authority_failure"
    assert record["typed_op_plan"] is None
    assert record["audit"]["expected_receipt"] == {
        "required": False,
        "kind": "none",
        "status": "no_effect",
    }
