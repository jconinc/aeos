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
    def verify_authority_bundle(self, digest: str) -> bool:
        return digest == "c" * 64

    def verify_source_heads(self, source_head_pins: dict[str, str]) -> bool:
        return bool(source_head_pins)

    def current_subject_revision(self, subject: Any) -> str:
        return str(subject.revision)

    def verify_research_receipt(self, evidence: Any) -> bool:
        return bool(evidence.research_receipt_digest)


class EchoingModel:
    def __init__(self, selected_id: str, *, citations: tuple[str, ...]) -> None:
        self.selected_id = selected_id
        self.citations = citations

    def choose(self, request: ModelChoiceRequest) -> ModelDecision:
        return ModelDecision(
            candidate_id=self.selected_id,
            rationale="The same exact evidence governs the unit in either ordering.",
            citations=self.citations,
            confidence=0.9,
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
            retained_output={"candidate_id": self.selected_id, "citations": list(self.citations)},
        )


def source_fixtures():  # type: ignore[no-untyped-def]
    require_pinned_source()
    from claude_coord.tests import test_canon_decision

    return test_canon_decision


def policy(*, model: bool = False) -> AuthorityPolicy:
    from aeos_kernel import stable_fingerprint

    return AuthorityPolicy(
        policy_id="multiagent-canon-decision",
        policy_version="2",
        level=AuthorityLevel.AGENT_JUDGMENT if model else AuthorityLevel.DETERMINISTIC,
        intensity=DecisionIntensity.INTERNAL_EFFECT,
        allowed_boundary_tags=("wlg_graph_mutation",),
        permits_model_choice=model,
        max_model_calls=2 if model else 0,
        max_model_cost_minor_units=5 if model else 0,
        model_provider="configured-reasoner" if model else "",
        model_id="reasoner-v1" if model else "",
        model_context_classification="internal-safe" if model else "",
        model_generation_parameters_digest=stable_fingerprint({"temperature": 0})
        if model
        else "",
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


def map_candidate(source_candidate: Any):  # type: ignore[no-untyped-def]
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
        )
    )


def test_shadow_manifest_pins_the_actual_source_fixture_and_forbids_effects() -> None:
    manifest = json.loads(PARITY_MANIFEST.read_text(encoding="utf-8"))
    source_fixtures()
    assert manifest["source_commit"] == PINNED_HEAD
    assert manifest["effect_policy"] == "read_only_shadow_no_effect_execution"
    assert set(manifest["cases"]) == {
        "entailed_selection",
        "fabricated_citation",
        "ambiguous_entailment",
        "reverse_order_consensus",
    }


def test_pinned_entailed_fixture_has_same_candidate_and_projection() -> None:
    source = source_fixtures()
    source_packet = source._packet()
    source_candidate = source._cand("link_target", "t1", ["e1"])
    old = source._run(source_packet, [source_candidate], model_call=source._no_model)
    packet = map_packet(source_packet)
    candidate = map_candidate(source_candidate)
    new = DecisionEngine(verifier=ParityVerifier(), clock=FixedClock()).decide(
        packet, (candidate,)
    )
    projected = to_wlg_decision_record(new, packet=packet, candidate=candidate)
    assert old.selection_mode == new.selection_mode == "auto_entailed"
    assert old.decision == projected["decision"] == candidate.action
    assert old.typed_op_plan is not None and candidate.effect is not None


def test_pinned_red_plants_refuse_without_an_effect() -> None:
    source = source_fixtures()
    source_packet = source._packet()
    nonentailed = source._cand("link_target", "t1", ["e1"], entailed=False)
    old_citation = source._run(
        source_packet,
        [nonentailed],
        model_call=lambda _system, _prompt: source._pick(nonentailed, citations=["ghost"]),
    )
    packet = map_packet(source_packet, model=True)
    candidate = map_candidate(nonentailed)
    new_citation = DecisionEngine(
        verifier=ParityVerifier(),
        clock=FixedClock(),
        model_gateway=EchoingModel(candidate.candidate_id, citations=("ghost",)),
    ).decide(packet, (candidate,))
    assert old_citation.typed_op_plan is None
    assert new_citation.status is DecisionStatus.REFUSED
    assert new_citation.refusal is not None
    assert new_citation.refusal.code is RefusalCode.MODEL_INVALID

    source_packet = source._packet(evs=[source._ev("e1"), source._ev("e2")])
    source_candidates = (
        source._cand("link_target", "t1", ["e1"]),
        source._cand("link_target", "t2", ["e2"]),
    )
    old_ambiguous = source._run(
        source_packet,
        list(source_candidates),
        model_call=source._no_model,
    )
    packet = map_packet(source_packet)
    candidates = tuple(map_candidate(item) for item in source_candidates)
    new_ambiguous = DecisionEngine(verifier=ParityVerifier(), clock=FixedClock()).decide(
        packet, candidates
    )
    assert old_ambiguous.typed_op_plan is None
    assert new_ambiguous.refusal is not None
    assert new_ambiguous.refusal.code is RefusalCode.AMBIGUOUS_ENTAILMENT


def test_pinned_reverse_order_consensus_selects_the_same_candidate() -> None:
    source = source_fixtures()
    source_packet = source._packet(evs=[source._ev("e1"), source._ev("e2")])
    first = source._cand("link_target", "t1", ["e1"], entailed=False)
    second = source._cand("link_target", "t2", ["e2"], entailed=False)
    calls = {"count": 0}

    def stable_choice(_system: str, _prompt: str) -> dict[str, Any]:
        calls["count"] += 1
        return source._with_model_identity(
            source._pick(second, citations=["e2"]),
            prompt_hash=str(calls["count"]) * 64,
            params_hash=str(calls["count"] + 2) * 64,
        )

    old = source._run(source_packet, [first, second], model_call=stable_choice)
    packet = map_packet(source_packet, model=True)
    candidates = (map_candidate(first), map_candidate(second))
    selected_id = map_candidate(second).candidate_id
    new = DecisionEngine(
        verifier=ParityVerifier(),
        clock=FixedClock(),
        model_gateway=EchoingModel(selected_id, citations=("e2",)),
    ).decide(packet, candidates)
    assert old.selection_mode == new.selection_mode == "model_eligible"
    assert old.typed_op_plan is not None
    assert new.selected_candidate_id == selected_id
