from __future__ import annotations

from typing import Any

import pytest

from aeos_kernel import (
    DecisionEngine,
    EvidenceItem,
    ModelDecision,
    RefusalCode,
    SourceRef,
    build_evidence_item,
    candidate_set_digest,
    decision_facts_evidence,
    principle_set_evidence,
    stable_fingerprint,
)
from aeos_kernel.errors import ContractError
from tests.factories import (
    NOW,
    AcceptingVerifier,
    FixedClock,
    ScriptedModel,
    candidate,
    evidence,
    packet,
    policy,
    subject,
)
from tests.test_schemas import validator


def rule(
    principle_id: str,
    kind: str,
    rank: int,
    area: str,
    *,
    requires: dict[str, Any] | None = None,
    when: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "principle_id": principle_id,
        "kind": kind,
        "rank": rank,
        "area": area,
        "applies_to": ["growth"],
        "statement": f"Doctrine words for {principle_id}.",
        "source": "Test doctrine",
        "when": when,
        "requires": requires,
    }


HONEST_PROOF = rule(
    "honest-proof", "gate", 1, "honesty",
    requires={"fact": "candidate.proof_verified", "op": "eq", "value": True},
)
USEFUL_FIRST = rule(
    "useful-first", "prefer", 3, "usefulness",
    requires={"fact": "candidate.useful", "op": "eq", "value": True},
)
LIMITING_LINK = rule(
    "limiting-link", "prefer", 5, "focus",
    requires={"fact": "candidate.focus", "op": "eq", "fact2": "context.focus"},
)
SMALLEST_TEST = rule("smallest-test", "judge", 4, "focus")
TRUST_FIRST = rule("trust-first", "judge", 2, "honesty")
PRELAUNCH_NO_PAID = rule(
    "prelaunch-no-paid", "gate", 1, "honesty",
    when={"fact": "context.stage", "op": "eq", "value": "prelaunch"},
    requires={"fact": "candidate.paid", "op": "eq", "value": False},
)
CONFLICT_ORDER = ["safety", "brand", "usefulness", "repeatability", "tactic"]


def rules(*principles: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "aeos.principle-set@1",
        "set_id": "test-growth",
        "version": "1",
        "conflict_order": CONFLICT_ORDER,
        "decision_types": {"growth": ["focus", "honesty"]},
        "principles": list(principles),
    }


def decide(
    principles: list[dict[str, Any]],
    facts: dict[str, dict[str, Any]],
    *,
    model: ScriptedModel,
    context: dict[str, Any] | None = None,
    decision_type: str = "growth",
    set_item: EvidenceItem | None = None,
    with_facts: bool = True,
):
    owner = subject(model_allowed=True)
    items = [
        evidence(model_allowed=True),
        set_item or principle_set_evidence(rules(*principles), subject=owner, observed_at=NOW),
    ]
    if with_facts:
        items.append(
            decision_facts_evidence(
                decision_type=decision_type,
                context=context if context is not None else {"focus": "utility"},
                candidates=facts,
                subject=owner,
                observed_at=NOW,
            )
        )
    options = tuple(candidate(name, entailed=False) for name in facts)
    engine = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock(), model_gateway=model)
    return engine.decide(
        packet(items=tuple(items), authority_policy=policy(model=True, human=False)), options
    )


def test_a_gate_removes_an_option_before_the_model_sees_it() -> None:
    model = ScriptedModel(["a"], principle_ids=("smallest-test",))
    result = decide(
        [HONEST_PROOF, SMALLEST_TEST],
        {"a": {"proof_verified": True}, "b": {"proof_verified": False}},
        model=model,
    )
    assert result.selected_candidate_id == "a"
    assert [item.candidate_id for item in model.requests[0].candidates] == ["a"]
    assert "Ruled out by principles: b (fails honest-proof)." in result.explanation


def test_a_preference_narrows_the_options_and_the_answer_cites_the_pack() -> None:
    model = ScriptedModel(["a"])
    result = decide(
        [HONEST_PROOF, LIMITING_LINK],
        {
            "a": {"proof_verified": True, "focus": "utility"},
            "b": {"proof_verified": True, "focus": "retention_and_renewal"},
        },
        model=model,
    )
    assert result.selected_candidate_id == "a"
    assert len(model.requests) == 1
    assert "b (not preferred under limiting-link)" in result.explanation
    assert result.evidence_ids == ("e1", "aeos-principle-set", "aeos-decision-facts")


def test_a_higher_ranked_preference_narrows_first() -> None:
    model = ScriptedModel(["b"])
    result = decide(
        [HONEST_PROOF, LIMITING_LINK, USEFUL_FIRST],
        {
            "a": {"proof_verified": True, "focus": "utility", "useful": False},
            "b": {"proof_verified": True, "focus": "retention_and_renewal", "useful": True},
        },
        model=model,
    )
    assert result.selected_candidate_id == "b"
    assert [item.candidate_id for item in model.requests[0].candidates] == ["b"]


def test_a_missing_context_fact_refuses_and_names_it() -> None:
    model = ScriptedModel(["a"])
    result = decide(
        [PRELAUNCH_NO_PAID, LIMITING_LINK],
        {"a": {"paid": False, "focus": "utility"}},
        model=model,
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MISSING_FACT
    assert result.refusal.missing_premise == "context.stage"
    assert model.requests == []


def test_an_option_missing_a_fact_is_ruled_out_and_named() -> None:
    kept = decide(
        [HONEST_PROOF, LIMITING_LINK],
        {"a": {"proof_verified": True, "focus": "utility"}, "b": {"focus": "utility"}},
        model=ScriptedModel(["a"]),
    )
    assert kept.selected_candidate_id == "a"
    assert "b (honest-proof needs candidate.proof_verified)" in kept.explanation
    none_left = decide(
        [HONEST_PROOF, LIMITING_LINK], {"b": {"focus": "utility"}}, model=ScriptedModel(["b"])
    )
    assert none_left.refusal is not None
    assert none_left.refusal.code is RefusalCode.MISSING_FACT
    assert none_left.refusal.missing_premise == "b: candidate.proof_verified"


def test_a_required_area_without_a_rule_refuses_with_missing_principle() -> None:
    result = decide([HONEST_PROOF], {"a": {"proof_verified": True}}, model=ScriptedModel(["a"]))
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MISSING_PRINCIPLE
    assert result.refusal.missing_premise == (
        "decision type 'growth' has no principle in force for area(s): focus"
    )
    validator("Recommendation").validate(result.as_dict())


def test_an_uncovered_decision_type_refuses_with_missing_principle() -> None:
    result = decide(
        [HONEST_PROOF, SMALLEST_TEST],
        {"a": {"proof_verified": True}},
        model=ScriptedModel(["a"]),
        decision_type="mail",
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MISSING_PRINCIPLE
    assert result.refusal.missing_premise == "no principle set covers decision type 'mail'"


def test_without_a_pack_the_model_request_is_unchanged() -> None:
    model = ScriptedModel(["candidate-1"])
    option = candidate(entailed=False)
    decision_packet = packet(
        items=(evidence(model_allowed=True),), authority_policy=policy(model=True, human=False)
    )
    engine = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock(), model_gateway=model)
    result = engine.decide(decision_packet, (option,))
    request = model.requests[0]
    assert request.principles == () and request.conflict_order == ()
    assert request.prompt_digest == stable_fingerprint(
        {
            "contract": "aeos.model-choice@2",
            "packet_digest": decision_packet.packet_digest,
            "candidate_set_digest": candidate_set_digest((option,)),
            "candidate_order": ["candidate-1"],
            "attempt": 1,
            "context_classification": "internal-safe",
        }
    )
    assert result.evidence_ids == ("e1",)


def test_the_model_sees_judge_rules_in_rank_order_and_must_name_one_in_force() -> None:
    facts = {"a": {"proof_verified": True}, "b": {"proof_verified": True}}
    principles = [HONEST_PROOF, SMALLEST_TEST, TRUST_FIRST]
    model = ScriptedModel(["a", "a"], principle_ids=("smallest-test",))
    result = decide(principles, facts, model=model)
    assert result.selected_candidate_id == "a"
    assert [brief.principle_id for brief in model.requests[0].principles] == [
        "trust-first",
        "smallest-test",
    ]
    assert model.requests[0].conflict_order == tuple(CONFLICT_ORDER)
    for named in (("made-up",), ()):
        bad = decide(principles, facts, model=ScriptedModel(["a", "a"], principle_ids=named))
        assert bad.refusal is not None
        assert bad.refusal.code is RefusalCode.MODEL_INVALID


def test_the_model_can_name_a_missing_fact_instead_of_choosing() -> None:
    model = ScriptedModel([""], escalation=(RefusalCode.MISSING_FACT, "whether buying is on"))
    result = decide(
        [HONEST_PROOF, SMALLEST_TEST],
        {"a": {"proof_verified": True}, "b": {"proof_verified": True}},
        model=model,
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MISSING_FACT
    assert result.refusal.missing_premise == "whether buying is on"
    assert len(model.requests) == 1 and len(result.model_calls) == 1
    identity = result.model_calls[0]
    for code, chosen in ((RefusalCode.MISSING_FACT, "a"), (RefusalCode.HUMAN_REQUIRED, "")):
        with pytest.raises(ContractError):
            ModelDecision(
                candidate_id=chosen,
                rationale="A rule needs a fact.",
                citations=(),
                confidence=0.9,
                identity=identity,
                retained_output={},
                escalation=code,
                missing_premise="whether buying is on",
            )


def test_a_second_call_that_names_a_missing_principle_refuses_with_both_calls() -> None:
    model = ScriptedModel(
        ["a", ""],
        principle_ids=("smallest-test",),
        escalation=(RefusalCode.MISSING_PRINCIPLE, "no rule weighs price against reach"),
    )
    result = decide(
        [HONEST_PROOF, SMALLEST_TEST],
        {"a": {"proof_verified": True}, "b": {"proof_verified": True}},
        model=model,
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.MISSING_PRINCIPLE
    assert len(result.model_calls) == 2


@pytest.mark.parametrize(
    "broken",
    [
        {**HONEST_PROOF, "requires": {"fact": "candidate.useful", "op": "like", "value": 1}},
        {**HONEST_PROOF, "when": {"fact": "candidate.paid", "op": "eq", "value": False}},
    ],
)
def test_a_malformed_pack_is_an_invalid_packet(broken: dict[str, Any]) -> None:
    raw = rules(broken, SMALLEST_TEST)
    with pytest.raises(ContractError):
        principle_set_evidence(raw, subject=subject(model_allowed=True), observed_at=NOW)
    set_item = build_evidence_item(
        evidence_id="aeos-principle-set",
        source_tier="standard",
        vertical_id="wema",
        tenant_id="wema",
        subject_id="article-1",
        subject_revision="1",
        payload=raw,
        source_ref=SourceRef("aeos_principle_set", "test-growth", "1", "b" * 64),
        observed_at=NOW,
        allowed_uses=("decision", "model"),
    )
    result = decide(
        [], {"a": {"proof_verified": True}}, model=ScriptedModel(["a"]), set_item=set_item
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.INVALID_PACKET


def test_a_pack_without_its_facts_is_an_invalid_packet() -> None:
    result = decide(
        [HONEST_PROOF, SMALLEST_TEST],
        {"a": {"proof_verified": True}},
        model=ScriptedModel(["a"]),
        with_facts=False,
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.INVALID_PACKET
