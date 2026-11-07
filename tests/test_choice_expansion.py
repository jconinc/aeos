"""Host-expanded reviewed choices, specification 0.27.0."""

from dataclasses import asdict, replace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel import (
    ContractError,
    DecisionEngine,
    ExpandedModelChoice,
    ModelCallIdentity,
    ModelChoiceFieldDiff,
    ModelReview,
    ModelReviewIssue,
    RefusalCode,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
    canonical_json,
    decision_facts_evidence,
    principle_set_evidence,
    stable_fingerprint,
)
from aeos_kernel.schemas import load_schema
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
from tests.test_graph import snapshot
from tests.test_principles import HONEST_PROOF, SMALLEST_TEST, rules


class Expansion:
    def __init__(self, *, mismatch=False, invalid=False):
        self.mismatch = mismatch
        self.invalid = invalid

    def __bool__(self):
        return False

    def expand(self, request, decision):
        if self.invalid:
            raise ValueError("invalid native expansion")
        choice = {"candidate": decision.candidate_id, "prose": f"answer {request.attempt}"}
        semantic = {
            "candidate": decision.candidate_id,
            "change": self.mismatch and request.attempt == 2,
        }
        return ExpandedModelChoice(
            request.attempt,
            "example@1",
            request.prompt_digest,
            "a" * 64,
            "b" * 64,
            choice,
            canonical_json(choice),
            semantic,
            stable_fingerprint(semantic),
            stable_fingerprint(choice),
        )

    def diff(self, proposed, corroborating):
        return (
            ModelChoiceFieldDiff(
                "prose",
                True,
                proposed.expanded_choice["prose"],
                True,
                corroborating.expanded_choice["prose"],
            ),
        )


class RecordingModel(ScriptedModel):
    def __init__(self, stale_call=None):
        super().__init__(["candidate-1"] * 4, principle_ids=("smallest-test",))
        self.stale_call = stale_call
        self.decisions = []

    def choose(self, request):
        decision = super().choose(request)
        if len(self.requests) == self.stale_call:
            decision = replace(
                decision, identity=replace(decision.identity, attempt=request.attempt - 1)
            )
        self.decisions.append(decision)
        return decision


class Reviews:
    def __init__(self, correction=False):
        self.requests = []
        self.correction = correction

    def review(self, request):
        self.requests.append(request)
        issue = ModelReviewIssue(
            "substantive_disagreement", "smallest-test", ("e1",), "candidate-1", "Revise."
        )
        issues = (issue,) if self.correction and len(self.requests) == 1 else ()
        verdict = "correct" if issues else "accept"
        output = {
            "verdict": verdict,
            "issues": [{**asdict(item), "fact_refs": list(item.fact_refs)} for item in issues],
            "missing_premise": None,
        }
        identity = ModelCallIdentity(
            request.provider,
            request.model_id,
            request.prompt_digest,
            request.generation_parameters_digest,
            request.context_classification,
            request.attempt,
            cost_minor_units=1,
        )
        return ModelReview(verdict, issues, None, identity, output)


def run(*, expansion=None, correction=False, budget=6, legacy=False, stale_call=None):
    graph = snapshot()
    node = graph.nodes[0]
    owner = subject(model_allowed=True)
    first_evidence = evidence(model_allowed=True)
    if not legacy:
        owner = replace(
            owner,
            vertical_id=graph.vertical_id,
            tenant_id=graph.tenant_id,
            subject_id=node.entity_id,
            subject_kind=node.kind,
            revision=node.revision,
            content_digest=node.content_digest,
            source_refs=(
                SourceRef("graph_node", node.entity_id, node.revision, node.content_digest),
            ),
            attributes=dict(node.properties),
        )
        first_evidence = build_evidence_item(
            evidence_id="e1",
            source_tier="host_state",
            vertical_id=graph.vertical_id,
            tenant_id=graph.tenant_id,
            subject_id=node.entity_id,
            subject_revision=node.revision,
            payload={"edge": graph.edges[0].edge_id, "project": graph.project_id},
            source_ref=SourceRef(
                "graph_snapshot", graph.project_id, str(graph.generation), graph.snapshot_digest
            ),
            observed_at=NOW,
            allowed_uses=("decision", "model"),
        )
    items = (
        first_evidence,
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
        max_model_calls=budget,
        max_model_cost_minor_units=6,
        require_model_review=True,
    )
    if legacy:
        current_packet = packet(items=items, authority_policy=reviewed)
        options = (
            candidate("candidate-1", entailed=False),
            candidate("candidate-2", entailed=False),
        )
    else:
        current_packet = build_decision_packet(
            packet_id="packet-1",
            subject=owner,
            evidence=items,
            authority_bundle_digest="c" * 64,
            policy=reviewed,
            allowed_actions=("improve_answer", "improve_description"),
            source_head_pins=graph.source_head_pins,
            adapter_id="example.graph",
            adapter_version="1",
            created_at=NOW,
        )
        options = tuple(
            replace(
                item,
                effect=replace(
                    item.effect,
                    operation="example.graph.propose_revision",
                    parameters={"entity_id": node.entity_id},
                ),
            )
            for item in (
                candidate("candidate-1", entailed=False),
                candidate("candidate-2", entailed=False),
            )
        )
    model = RecordingModel(stale_call)
    reviews = Reviews(correction)
    result = DecisionEngine(
        AcceptingVerifier(),
        FixedClock(),
        model,
        review_gateway=reviews,
        choice_expansion_port=expansion,
    ).decide(
        current_packet,
        options,
    )
    return result, model, reviews


def test_agreement_keeps_both_expansions_and_binds_critic_digest():
    result, model, reviews = run(expansion=Expansion())
    assert result.selected_candidate_id == "candidate-1"
    first, second = result.model_choice_expansions
    assert [first.expanded_choice["prose"], second.expanded_choice["prose"]] == [
        "answer 1",
        "answer 2",
    ]
    assert list(result.model_outputs[:2]) == [
        {"candidate_id": "candidate-1", "citations": ["e1"]},
        {"candidate_id": "candidate-1", "citations": ["e1"]},
    ]
    req = reviews.requests[0]
    assert (req.packet.subject.vertical_id, req.packet.subject.tenant_id) == (
        "example",
        "tenant-one",
    )
    assert req.packet.source_head_pins == snapshot().source_head_pins
    assert req.contract_version == "aeos.model-review@2"
    assert (req.proposed_expansion, req.corroborating_expansion) == (first, second)
    assert req.semantic_payload == first.semantic_payload == second.semantic_payload
    assert req.expansion_diff == (
        ModelChoiceFieldDiff("prose", True, "answer 1", True, "answer 2"),
    )
    data = {
        "contract": req.contract_version,
        "purpose": "review",
        "attempt": req.attempt,
        "packet_digest": req.packet.packet_digest,
        "candidate_set_digest": result.candidate_set_digest,
        "candidate_order": list(req.candidate_order),
        "proposed_candidate_id": req.proposed_candidate_id,
        "proposed_citations": list(req.proposed_citations),
        "principles": [asdict(p) for p in req.principles],
        "deterministic_rule_results": [list(row) for row in req.deterministic_rule_results],
        "allowed_fact_refs": list(req.allowed_fact_refs),
        "context_classification": req.context_classification,
        "proposed_expansion": first.as_dict(),
        "corroborating_expansion": second.as_dict(),
        "semantic_payload": req.semantic_payload,
        "expansion_diff": [asdict(x) for x in req.expansion_diff],
    }
    assert req.prompt_digest == stable_fingerprint(data) == result.model_request_digests[2]
    assert first.prompt_digest == model.requests[0].prompt_digest
    assert second.prompt_digest == model.requests[1].prompt_digest


def test_semantic_mismatch_refuses_before_review_and_retains_pair():
    result, model, reviews = run(expansion=Expansion(mismatch=True))
    assert result.refusal.code is RefusalCode.MODEL_DISAGREEMENT
    assert (
        len(model.requests) == len(result.model_outputs) == len(result.model_choice_expansions) == 2
    )
    assert not reviews.requests


def test_invalid_expansion_retains_raw_call_without_repair():
    result, model, reviews = run(expansion=Expansion(invalid=True))
    assert result.refusal.code is RefusalCode.MODEL_INVALID
    assert len(model.requests) == len(result.model_calls) == len(result.model_outputs) == 1
    assert result.model_outputs[0]["candidate_id"] == "candidate-1"
    assert not result.model_choice_expansions and not reviews.requests


@pytest.mark.parametrize(
    ("stale_call", "expected_calls", "expected_expansions", "expected_reviews"),
    [(2, 2, [1], 0), (4, 5, [1, 2, 4], 1)],
)
def test_stale_chooser_identity_retains_prior_expansions_and_raw_calls(
    stale_call, expected_calls, expected_expansions, expected_reviews
):
    result, model, reviews = run(
        expansion=Expansion(), correction=stale_call == 4, stale_call=stale_call
    )
    assert result.refusal.code is RefusalCode.MODEL_INVALID
    assert len(model.requests) == stale_call
    assert len(result.model_calls) == len(result.model_outputs) == expected_calls
    assert [item.attempt for item in result.model_choice_expansions] == expected_expansions
    assert result.model_calls[-1].attempt == model.requests[-1].attempt - 1
    assert result.model_outputs[-1]["candidate_id"] == "candidate-1"
    assert len(reviews.requests) == expected_reviews


def test_correction_retains_six_calls_and_incomplete_phase_never_starts():
    result, model, reviews = run(expansion=Expansion(), correction=True)
    assert result.selected_candidate_id == "candidate-1"
    assert [c.attempt for c in result.model_calls] == [1, 2, 3, 4, 5, 6]
    assert [x.attempt for x in result.model_choice_expansions] == [1, 2, 4, 5]
    assert len(model.requests) == 4 and len(reviews.requests) == 2
    assert model.requests[2].correction_issues[0].code == "substantive_disagreement"
    result, model, reviews = run(expansion=Expansion(), correction=True, budget=5)
    assert result.refusal.code is RefusalCode.MODEL_BUDGET_EXCEEDED
    assert len(result.model_calls) == 3 and len(model.requests) == 2 and len(reviews.requests) == 1


def test_immutable_values_and_recommendation_schema_bindings():
    result, model, _ = run(expansion=Expansion())
    first = result.model_choice_expansions[0]
    with pytest.raises(TypeError):
        first.expanded_choice["prose"] = "tampered"
    nested = {"nodes": [{"id": "one"}]}
    frozen = replace(first, expanded_choice=nested, canonical_expanded_json=canonical_json(nested))
    nested["nodes"][0]["id"] = "changed"
    assert frozen.expanded_choice["nodes"][0]["id"] == "one"
    with pytest.raises(TypeError):
        frozen.expanded_choice["nodes"][0]["id"] = "changed"
    with pytest.raises(ContractError):
        replace(first, canonical_expanded_json="{}")
    with pytest.raises(ContractError):
        replace(first, semantic_fingerprint="0" * 64)
    with pytest.raises(ContractError):
        replace(result, model_choice_expansions=(replace(first, prompt_digest="0" * 64),))
    value = {"nested": [1]}
    diff = ModelChoiceFieldDiff("x", True, value, False, None)
    value["nested"].append(2)
    assert diff.proposed_value == {"nested": [1]}
    assert diff.as_dict()["proposed_value"] == {"nested": [1]}
    for version in ("v1", "v2"):
        bundle = load_schema("bundle.schema.json", version=version)
        validator = Draft202012Validator(
            {"$ref": "#/$defs/Recommendation", "$defs": bundle["$defs"]}
        )
        validator.validate(result.as_dict())
        bad = result.as_dict()
        bad["model_choice_expansions"][0]["attempt"] = 0
        with pytest.raises(ValidationError):
            validator.validate(bad)
    # The host must recompute from retained calls, not trust an edited sidecar.
    reconstructed = Expansion().expand(model.requests[0], model.decisions[0])
    assert reconstructed.as_dict() == first.as_dict()
    tampered = first.as_dict() | {"full_digest": "f" * 64}
    assert reconstructed.as_dict() != tampered


def test_no_port_preserves_old_head_recommendation_and_request_digests():
    # Captured from c3a2b5f0.26 with the same factories and review script.
    result, model, reviews = run(legacy=True)
    assert (
        stable_fingerprint(result.as_dict())
        == "fa0e109dbf9d104b8e2e6f25c4a4fe79ee1667af75237f78f4dc1d3025d500f4"
    )
    assert [x.prompt_digest for x in model.requests] == [
        "ef7604a0f50f7fdf49802a78b5407748fe241ddf11d7d7016556cc5affc19fb6",
        "4a4565448c452da0162c509c65b68bc4f5cf7d92426c960a60026c0c9a0c99ec",
    ]
    assert (
        reviews.requests[0].prompt_digest
        == "36850411306261a170ad1990373c1719bc525a7e021b4ec904b58150972a965b"
    )
