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


def test_typed_premise_refs_survive_a_model_stop_and_reject_mismatched_output() -> None:
    import pytest

    from aeos_kernel import ContractError

    class StopModel(ScriptedModel):
        def choose(self, request):
            original = super().choose(request)
            self.result = replace(
                original,
                premise_refs=("fact:source-current",),
                retained_output={
                    **original.retained_output, "premise_refs": ["fact:source-current"],
                },
            )
            return self.result

    model = StopModel([""], escalation=(RefusalCode.MISSING_FACT, "Source status is missing"))
    result = engine(model=model).decide(
        packet(authority_policy=policy(model=True)), (candidate(entailed=False),)
    )
    assert result.refusal is not None and result.refusal.code is RefusalCode.MISSING_FACT
    assert result.as_dict()["model_outputs"][0]["premise_refs"] == ["fact:source-current"]
    assert result.model_outputs[0]["premise_refs"] == ["fact:source-current"]

    class Mismatched(StopModel):
        def choose(self, request):
            return replace(super().choose(request), retained_output={"premise_refs": []})

    bad = Mismatched([""], escalation=(RefusalCode.MISSING_FACT, "Source status is missing"))
    refused = engine(model=bad).decide(
        packet(authority_policy=policy(model=True)), (candidate(entailed=False),)
    )
    assert refused.refusal is not None and refused.refusal.code is RefusalCode.MODEL_INVALID

    with pytest.raises(ContractError):
        replace(model.result, premise_refs=("fact:free text",))
    with pytest.raises(ContractError):
        replace(model.result, premise_refs=("fact:a", "fact:a"))
    with pytest.raises(ContractError):
        replace(model.result, premise_refs=["fact:a"])


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


def test_higher_authority_entailment_dominates_lower_tier_without_ambiguity() -> None:
    current_packet = packet(
        items=(
            evidence(evidence_id="legal", source_tier="legal"),
            evidence(evidence_id="graph", source_tier="graph"),
        )
    )
    candidates = (
        candidate("legal-choice", evidence_ids=("legal",), source_tier="legal"),
        candidate(
            "graph-choice",
            action="improve_description",
            evidence_ids=("graph",),
            source_tier="graph",
        ),
    )
    result = engine().decide(current_packet, candidates)
    assert result.selected_candidate_id == "legal-choice"
    assert result.selection_mode == "auto_entailed"
    assert result.rejected_alternatives == ("graph-choice",)


def test_model_pool_excludes_lower_authority_candidates() -> None:
    current_policy = policy(model=True)
    current_packet = packet(
        authority_policy=current_policy,
        items=(
            evidence(evidence_id="legal", source_tier="legal", model_allowed=True),
            evidence(evidence_id="canon", source_tier="canon", model_allowed=True),
        ),
    )
    candidates = (
        candidate(
            "legal-choice",
            evidence_ids=("legal",),
            source_tier="legal",
            entailed=False,
        ),
        candidate(
            "canon-choice",
            action="improve_description",
            evidence_ids=("canon",),
            source_tier="canon",
            entailed=False,
        ),
    )
    scripted = ScriptedModel(["legal-choice"], citations=("legal",))
    result = engine(model=scripted).decide(current_packet, candidates)
    assert result.selected_candidate_id == "legal-choice"
    assert [request.candidate_order for request in scripted.requests] == [("legal-choice",)]


def test_reviewed_choice_correction_keeps_evidence_and_rechecks_currency() -> None:
    from dataclasses import asdict

    from aeos_kernel import (
        ModelCallIdentity,
        ModelReview,
        ModelReviewIssue,
        decision_facts_evidence,
        principle_set_evidence,
    )
    from tests.factories import subject
    from tests.test_principles import HONEST_PROOF, SMALLEST_TEST, rules

    issue = ModelReviewIssue(
        "wrong_remedy", "smallest-test", ("e1",), "candidate-1", "Use the smaller remedy."
    )

    class Reviews:
        def __init__(self) -> None:
            self.requests = []

        def review(self, request):
            self.requests.append(request)
            issues = (issue,) if len(self.requests) == 1 else ()
            verdict = "correct" if issues else "accept"
            output = {
                "verdict": verdict,
                "issues": [{**asdict(item), "fact_refs": list(item.fact_refs)} for item in issues],
                "missing_premise": None,
            }
            return ModelReview(
                verdict,
                issues,
                None,
                ModelCallIdentity(
                    provider=request.provider,
                    model_id=request.model_id,
                    prompt_digest=request.prompt_digest,
                    generation_parameters_digest=request.generation_parameters_digest,
                    context_classification=request.context_classification,
                    attempt=request.attempt,
                    cost_minor_units=1,
                ),
                output,
            )

    owner = subject(model_allowed=True)
    items = (
        evidence(model_allowed=True),
        principle_set_evidence(rules(HONEST_PROOF, SMALLEST_TEST), subject=owner, observed_at=NOW),
        decision_facts_evidence(
            decision_type="growth",
            context={},
            candidates={
                "candidate-1": {"proof_verified": True},
                "candidate-2": {"proof_verified": True},
            },
            subject=owner,
            observed_at=NOW,
        ),
    )
    reviewed = replace(
        policy(model=True),
        max_model_calls=6,
        max_model_cost_minor_units=6,
        require_model_review=True,
    )
    model = ScriptedModel(
        ["candidate-1", "candidate-1", "candidate-2", "candidate-2"],
        principle_ids=("smallest-test",),
    )
    reviews = Reviews()
    result = DecisionEngine(
        AcceptingVerifier(), FixedClock(), model, review_gateway=reviews
    ).decide(
        packet(items=items, authority_policy=reviewed),
        (candidate("candidate-1", entailed=False), candidate("candidate-2", entailed=False)),
    )
    assert result.selected_candidate_id == "candidate-2"
    assert result.model_call_purposes == (
        "choose",
        "choose",
        "review",
        "choose",
        "choose",
        "review",
    )
    assert [call.attempt for call in result.model_calls] == [1, 2, 3, 4, 5, 6]
    assert result.model_request_digests == tuple(call.prompt_digest for call in result.model_calls)
    assert model.requests[2].correction_issues == (issue,)
    assert {p.principle_id for p in reviews.requests[0].principles} == {
        "honest-proof",
        "smallest-test",
    }
    assert reviews.requests[0].deterministic_rule_results == (
        ("honest-proof:candidate-1", "passed"),
        ("honest-proof:candidate-2", "passed"),
    )
    assert reviews.requests[0].allowed_fact_refs == (
        "e1",
        "aeos-principle-set",
        "aeos-decision-facts",
    )
    assert result.as_dict()["model_protocol_version"] == "aeos.reviewed-choice@1"

    review_request = reviews.requests[0]
    forged = replace(issue, fact_refs=("invented",))
    forged_output = {
        "verdict": "correct",
        "issues": [{**asdict(forged), "fact_refs": list(forged.fact_refs)}],
        "missing_premise": None,
    }
    forged_review = ModelReview("correct", (forged,), None, result.model_calls[2], forged_output)
    invalid = DecisionEngine._validate_review(forged_review, review_request)
    assert invalid is not None and invalid.code is RefusalCode.MODEL_INVALID
    extra = replace(forged_review, retained_output={**forged_output, "unexpected": True})
    invalid = DecisionEngine._validate_review(extra, review_request)
    assert invalid is not None and invalid.code is RefusalCode.MODEL_INVALID
    typed_output = {
        "verdict": "missing_fact",
        "issues": [],
        "missing_premise": "Missing",
        "premise_refs": ["fact:source-current"],
    }
    typed_review = ModelReview(
        "missing_fact",
        (),
        "Missing",
        result.model_calls[2],
        typed_output,
        premise_refs=("fact:source-current",),
    )
    assert DecisionEngine._validate_review(typed_review, review_request) is None
    mismatch = replace(typed_review, premise_refs=("fact:another",))
    invalid = DecisionEngine._validate_review(mismatch, review_request)
    assert invalid is not None and invalid.code is RefusalCode.MODEL_INVALID
    absent = replace(typed_review, premise_refs=None)
    invalid = DecisionEngine._validate_review(absent, review_request)
    assert invalid is not None and invalid.code is RefusalCode.MODEL_INVALID
    # The generic port enforces bounds too, independently of a host JSON parser.
    oversized = ModelReview(
        "missing_fact",
        (),
        "x" * 301,
        result.model_calls[2],
        {
            "verdict": "missing_fact",
            "issues": [],
            "missing_premise": "x" * 301,
        },
    )
    invalid = DecisionEngine._validate_review(oversized, review_request)
    assert invalid is not None and invalid.code is RefusalCode.MODEL_INVALID
    original_issues: list[dict[str, str]] = []
    original_output = {"verdict": "accept", "issues": original_issues, "missing_premise": None}
    immutable_review = ModelReview("accept", (), None, result.model_calls[2], original_output)
    original_issues.append({"code": "forged"})
    assert immutable_review.retained_output["issues"] == []

    verifier = AcceptingVerifier()

    class StaleAfterReview(Reviews):
        def review(self, request):
            result = super().review(request)
            verifier.source_heads_valid = False
            return result

    chooser = ScriptedModel(["candidate-1", "candidate-1"], principle_ids=("smallest-test",))
    stopped = DecisionEngine(
        verifier, FixedClock(), chooser, review_gateway=StaleAfterReview()
    ).decide(
        packet(items=items, authority_policy=reviewed),
        (candidate("candidate-1", entailed=False), candidate("candidate-2", entailed=False)),
    )
    assert stopped.refusal is not None and stopped.refusal.code is RefusalCode.STALE_INPUT
    assert len(chooser.requests) == 2
    assert stopped.model_call_purposes == ("choose", "choose", "review")


def test_reviewed_choice_refuses_without_review_or_phase_budget() -> None:
    reviewed = replace(policy(model=True), require_model_review=True)
    model = ScriptedModel(["candidate-1", "candidate-1"])
    options = (candidate(entailed=False),)
    result = engine(model=model).decide(packet(authority_policy=reviewed), options)
    assert result.refusal is not None and result.refusal.code is RefusalCode.MODEL_REQUIRED
    assert not model.requests

    class UnusedReviewer:
        def review(self, request):
            raise AssertionError("budget refusal must happen before review")

    result = DecisionEngine(
        AcceptingVerifier(), FixedClock(), model, review_gateway=UnusedReviewer()
    ).decide(packet(authority_policy=reviewed), options)
    assert result.refusal is not None and result.refusal.code is RefusalCode.MODEL_BUDGET_EXCEEDED
    assert not model.requests
    assert "require_model_review" not in policy(model=True).as_dict()
    assert "model_protocol_version" not in engine().decide(packet(), (candidate(),)).as_dict()
