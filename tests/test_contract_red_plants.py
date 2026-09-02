from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from aeos_kernel import (
    AuthorityLevel,
    AuthorizationContext,
    AuthorizedEffect,
    ContractError,
    DecisionEngine,
    DecisionIntensity,
    DecisionStatus,
    EffectReceipt,
    EffectStatus,
    EffectTemplate,
    EntailmentProof,
    HumanAttestation,
    HumanResponse,
    ModelCallIdentity,
    ModelDecision,
    OutcomeStatus,
    PrivacyClass,
    Recommendation,
    Refusal,
    RefusalCode,
    RegisteredOperation,
    authorize_effect,
    build_outcome_evidence,
    candidate_set_digest,
    content_digest,
    stable_fingerprint,
)
from aeos_kernel import contracts as contract_exports
from aeos_kernel.canonical import without_keys
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


def decided():  # type: ignore[no-untyped-def]
    decision_packet = packet()
    selected = candidate()
    recommendation = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        decision_packet, (selected,)
    )
    return decision_packet, selected, recommendation


def use_attestation(recommendation: Recommendation) -> HumanAttestation:
    return HumanAttestation(
        attestation_id="attestation-1",
        actor_id="founder-1",
        capacity="founder",
        decision_id=recommendation.decision_id,
        decision_revision=1,
        recommendation_digest=recommendation.digest,
        subject_digest="a" * 64,
        projection_digest="b" * 64,
        response=HumanResponse.USE_THIS,
        idempotency_key="key-1",
        decided_at=NOW,
    )


def registered() -> RegisteredOperation:
    return RegisteredOperation(
        operation="wema.article.create_revision",
        operation_version="1",
        parameter_names=frozenset({"article_id", "expected_digest", "draft"}),
        boundary_tags=frozenset({"content_revision"}),
        expected_postcondition="new_unapproved_article_revision",
        intensity=DecisionIntensity.INTERNAL_EFFECT,
    )


def ready_context(
    decision_packet,  # type: ignore[no-untyped-def]
    recommendation: Recommendation,
    candidates,  # type: ignore[no-untyped-def]
    operation: RegisteredOperation | None = None,
) -> AuthorizationContext:
    current_operation = operation or registered()
    return AuthorizationContext(
        current_subject_revision=decision_packet.subject.revision,
        current_subject_digest=decision_packet.subject.content_digest,
        current_packet_digest=decision_packet.packet_digest,
        current_recommendation_digest=recommendation.digest,
        current_candidate_set_digest=candidate_set_digest(candidates),
        current_projection_digest="b" * 64,
        current_authority_bundle_digest=decision_packet.authority_bundle_digest,
        current_policy_digest=stable_fingerprint(decision_packet.policy.as_dict()),
        current_operation_digest=current_operation.digest,
        current_source_head_pins=dict(decision_packet.source_head_pins),
        current_adapter_id=decision_packet.adapter_id,
        current_adapter_version=decision_packet.adapter_version,
        verified_actor_id="founder-1",
        verified_capacity="founder",
        effects_enabled=True,
        provider_ready=True,
        available_cost_minor_units=0,
    )


def test_public_contract_module_and_canonical_byte_helpers_are_live() -> None:
    assert contract_exports.DecisionPacket is not None
    assert (
        content_digest(b"wema")
        == "47cc76f3af40dd2e46c3f65d4e97dc85e49a8c41e6aaa93b89eef30775f00f49"
    )
    assert without_keys({"one": 1, "two": 2}, "two") == {"one": 1}


def test_nested_contract_json_is_deeply_immutable() -> None:
    current_subject = subject()
    with pytest.raises(TypeError, match="immutable"):
        current_subject.attributes["new"] = True
    selected = candidate()
    assert selected.effect is not None
    with pytest.raises(TypeError, match="immutable"):
        selected.effect.parameters["draft"]["title"] = "changed"
    decision_packet = packet()
    with pytest.raises(TypeError, match="immutable"):
        decision_packet.source_head_pins["wema_git"] = "changed"


def test_v2_contract_red_plants_reject_unbounded_or_unknown_controls() -> None:
    with pytest.raises(ValueError, match="parameter_names"):
        replace(registered(), parameter_names=frozenset())
    with pytest.raises(ValueError, match="intensity"):
        replace(registered(), intensity=99)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="advisory"):
        replace(registered(), intensity=DecisionIntensity.ADVISORY)
    with pytest.raises(ValueError, match="external confirmation"):
        replace(registered(), requires_external_confirmation=True)
    with pytest.raises(ValueError, match="fanout"):
        replace(registered(), fanout_ceiling=0)

    decision_packet, selected, recommendation = decided()
    current = ready_context(decision_packet, recommendation, (selected,))
    with pytest.raises(ValueError, match="nonnegative"):
        replace(current, available_cost_minor_units=-1)
    with pytest.raises(ValueError, match="nonempty"):
        replace(current, current_source_head_pins={})

    with pytest.raises(ContractError, match="recognized"):
        replace(policy(), level="unknown")  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="unique"):
        replace(policy(), allowed_boundary_tags=("content_revision", "content_revision"))
    with pytest.raises(ContractError, match="human_required"):
        replace(
            policy(human=False),
            level=AuthorityLevel.HUMAN_REQUIRED,
            requires_human_attestation=False,
        )

    with pytest.raises(ContractError, match="fanout"):
        replace(selected.effect, fanout_ceiling=0)  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="unique"):
        replace(
            selected.effect,  # type: ignore[arg-type]
            boundary_tags=("content_revision", "content_revision"),
        )


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: subject(revision=""),
        lambda: EntailmentProof("host_state", (), "reason"),
        lambda: EffectTemplate("op", "1", {}, (), "post", True, cost_ceiling_minor_units=-1),
        lambda: ModelCallIdentity(
            "provider", "model", "bad", "f" * 64, "internal-safe", 1
        ),
        lambda: ModelCallIdentity(
            "provider", "model", "e" * 64, "f" * 64, "internal-safe", 0
        ),
        lambda: ModelDecision(
            "choice",
            "reason",
            ("e1",),
            1.1,
            ModelCallIdentity(
                "provider", "model", "e" * 64, "f" * 64, "internal-safe", 1
            ),
            {},
        ),
        lambda: HumanAttestation(
            "attestation",
            "actor",
            "founder",
            "decision",
            0,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            HumanResponse.USE_THIS,
            "key",
            NOW,
        ),
        lambda: HumanAttestation(
            "attestation",
            "actor",
            "founder",
            "decision",
            1,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            HumanResponse.SNOOZE,
            "key",
            NOW,
        ),
        lambda: HumanAttestation(
            "attestation",
            "actor",
            "founder",
            "decision",
            1,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            HumanResponse.USE_THIS,
            "key",
            NOW,
            snooze_until=NOW + timedelta(days=1),
        ),
    ],
)
def test_malformed_public_contracts_are_refused(constructor: object) -> None:
    with pytest.raises(ContractError):
        constructor()  # type: ignore[operator]


def test_recommendation_status_and_payload_must_agree() -> None:
    with pytest.raises(ContractError, match="requires a refusal"):
        Recommendation("decision", 1, DecisionStatus.REFUSED, "a" * 64, "b" * 64)
    with pytest.raises(ContractError, match="selected candidate"):
        Recommendation("decision", 1, DecisionStatus.PROPOSED, "a" * 64, "b" * 64)


def test_effect_and_outcome_contracts_refuse_impossible_values() -> None:
    with pytest.raises(ContractError, match="positive"):
        AuthorizedEffect(
            authorization_id="authorization",
            decision_id="decision",
            decision_revision=0,
            operation="operation",
            operation_version="1",
            operation_contract_digest="1" * 64,
            parameters={},
            boundary_tags=(),
            precondition_digest="a" * 64,
            expected_postcondition="postcondition",
            idempotency_key="key",
            authorized_at=NOW,
            authority_policy_digest="b" * 64,
            recommendation_digest="c" * 64,
            candidate_set_digest="d" * 64,
            projection_digest="e" * 64,
            source_head_pins_digest="f" * 64,
        )
    with pytest.raises(ContractError, match="postimage"):
        EffectReceipt(
            "receipt",
            "authorization",
            "decision",
            1,
            "operation",
            "1",
            "a" * 64,
            EffectStatus.APPLIED,
            NOW,
            actual_postimage_digest="bad",
        )
    with pytest.raises(ContractError, match="cannot end"):
        build_outcome_evidence(
            outcome_id="outcome",
            receipt_id="receipt",
            metric_id="metric",
            status=OutcomeStatus.NEUTRAL,
            window_started_at=NOW,
            window_ended_at=NOW - timedelta(seconds=1),
            observed_at=NOW,
            aggregate={},
            policy_digest="a" * 64,
        )


def test_effect_authorization_refusal_surface_is_closed() -> None:
    decision_packet, selected, recommendation = decided()
    human = use_attestation(recommendation)
    current_operation = registered()
    cases = (
        (
            replace(recommendation, packet_digest="f" * 64),
            selected,
            human,
            registered(),
            ready_context(
                decision_packet,
                replace(recommendation, packet_digest="f" * 64),
                (selected,),
            ),
            RefusalCode.STALE_INPUT,
        ),
        (
            replace(recommendation, selected_candidate_id="different"),
            selected,
            human,
            registered(),
            ready_context(
                decision_packet,
                replace(recommendation, selected_candidate_id="different"),
                (selected,),
            ),
            RefusalCode.CONFLICT,
        ),
        (
            recommendation,
            selected,
            human,
            registered(),
            replace(
                ready_context(decision_packet, recommendation, (selected,)),
                effects_enabled=False,
            ),
            RefusalCode.EFFECT_PRECONDITION_FAILED,
        ),
        (
            recommendation,
            selected,
            human,
            None,
            ready_context(decision_packet, recommendation, (selected,)),
            RefusalCode.EFFECT_NOT_REGISTERED,
        ),
        (
            recommendation,
            selected,
            human,
            replace(current_operation, boundary_tags=frozenset({"publish"})),
            ready_context(
                decision_packet,
                recommendation,
                (selected,),
                replace(current_operation, boundary_tags=frozenset({"publish"})),
            ),
            RefusalCode.BOUNDARY_NOT_AUTHORIZED,
        ),
        (
            recommendation,
            replace(
                selected,
                effect=replace(selected.effect, cost_ceiling_minor_units=1),  # type: ignore[arg-type]
            ),
            human,
            registered(),
            ready_context(decision_packet, recommendation, (selected,)),
            RefusalCode.CONFLICT,
        ),
        (
            recommendation,
            selected,
            replace(human, capacity="operator"),
            registered(),
            ready_context(decision_packet, recommendation, (selected,)),
            RefusalCode.HUMAN_ATTESTATION_INVALID,
        ),
        (
            recommendation,
            selected,
            replace(human, recommendation_digest="f" * 64),
            registered(),
            ready_context(decision_packet, recommendation, (selected,)),
            RefusalCode.HUMAN_ATTESTATION_INVALID,
        ),
    )
    for current_recommendation, current_candidate, current_human, operation, context, code in cases:
        result = authorize_effect(
            packet=decision_packet,
            recommendation=current_recommendation,
            candidates=(current_candidate,),
            attestation=current_human,
            operation=operation,
            context=context,
            idempotency_key="effect-key",
            authorized_at=NOW,
        )
        assert isinstance(result, Refusal)
        assert result.code is code


def test_model_policy_and_response_red_plants_fail_closed() -> None:
    candidates = (candidate(entailed=False),)
    model_policy = policy(model=True)
    no_gateway = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        packet(authority_policy=model_policy), candidates
    )
    assert no_gateway.refusal is not None
    assert no_gateway.refusal.code is RefusalCode.MODEL_REQUIRED

    with pytest.raises(ContractError, match="positive call ceiling"):
        replace(model_policy, max_model_calls=0)
    no_calls = replace(model_policy, max_model_calls=1)
    budget_candidates = (
        candidate("candidate-1", entailed=False),
        candidate("candidate-2", action="improve_description", entailed=False),
    )
    budget = DecisionEngine(
        verifier=AcceptingVerifier(),
        clock=FixedClock(),
        model_gateway=ScriptedModel(["candidate-1"]),
    ).decide(packet(authority_policy=no_calls), budget_candidates)
    assert budget.refusal is not None
    assert budget.refusal.code is RefusalCode.MODEL_BUDGET_EXCEEDED

    invented_citation = DecisionEngine(
        verifier=AcceptingVerifier(),
        clock=FixedClock(),
        model_gateway=ScriptedModel(["candidate-1"], citations=("not-in-packet",)),
    ).decide(packet(authority_policy=model_policy), candidates)
    assert invented_citation.refusal is not None
    assert invented_citation.refusal.code is RefusalCode.MODEL_INVALID


def test_packet_trust_red_plants_fail_before_selection() -> None:
    verifier = AcceptingVerifier()
    verifier.authority_valid = False
    authority = DecisionEngine(verifier=verifier, clock=FixedClock()).decide(
        packet(), (candidate(),)
    )
    assert authority.refusal is not None
    assert authority.refusal.code is RefusalCode.AUTHORITY_MISSING

    verifier = AcceptingVerifier()
    verifier.source_heads_valid = False
    heads = DecisionEngine(verifier=verifier, clock=FixedClock()).decide(packet(), (candidate(),))
    assert heads.refusal is not None
    assert heads.refusal.code is RefusalCode.STALE_INPUT


def test_evidence_red_plants_fail_before_selection() -> None:
    unknown = evidence(source_tier="made_up")
    prohibited = replace(evidence(), privacy_classification=PrivacyClass.PROHIBITED)
    tampered = replace(evidence(), payload={"changed": True})
    duplicate = (evidence(), evidence())
    research = evidence(
        source_tier="research",
        research_receipt_digest=stable_fingerprint({"receipt": "one"}),
    )
    verifier = AcceptingVerifier()
    verifier.research_valid = False
    cases = (
        (packet(items=(unknown,)), AcceptingVerifier(), RefusalCode.INVALID_EVIDENCE),
        (packet(items=(prohibited,)), AcceptingVerifier(), RefusalCode.INVALID_EVIDENCE),
        (packet(items=(tampered,)), AcceptingVerifier(), RefusalCode.INVALID_EVIDENCE),
        (packet(items=duplicate), AcceptingVerifier(), RefusalCode.INVALID_EVIDENCE),
        (packet(items=(research,)), verifier, RefusalCode.INVALID_EVIDENCE),
    )
    for decision_packet, trust, expected in cases:
        result = DecisionEngine(verifier=trust, clock=FixedClock()).decide(
            decision_packet, (candidate(),)
        )
        assert result.refusal is not None
        assert result.refusal.code is expected


def test_duplicate_candidate_identity_and_empty_set_fail_closed() -> None:
    duplicate = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        packet(), (candidate(), candidate())
    )
    assert duplicate.refusal is not None
    assert duplicate.refusal.code is RefusalCode.INVALID_PACKET
    empty = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(packet(), ())
    assert empty.refusal is not None
    assert empty.refusal.code is RefusalCode.NO_ELIGIBLE_CANDIDATE


def test_advisory_policy_cannot_smuggle_an_effect() -> None:
    advisory = policy(intensity=DecisionIntensity.ADVISORY)
    result = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        packet(authority_policy=advisory), (candidate(),)
    )
    assert result.refusal is not None
    assert result.refusal.code is RefusalCode.NO_ELIGIBLE_CANDIDATE
