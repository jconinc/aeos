"""The kernel's refusal branches, each seen to fire once by its code and its sentence.

The 5 September coverage run (92 % against `fail_under = 90`) covered the decision machinery on
the path that says yes: `effect_authorization` 91 %, `verification` 89 %, `effects` 88 %,
`evidence` 88 % — and almost every miss is a refusal or a contract error. Wema's marketing
effects run through these fences. Each case below is one input wrong against an otherwise
authorized effect, verified packet or valid contract, asserting the exact code and reason,
beside a control that the unchanged input passes.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from aeos_kernel import (
    AuthorityLevel,
    AuthorizationContext,
    ContractError,
    DecisionEngine,
    EffectReceipt,
    EffectStatus,
    HumanAttestation,
    HumanResponse,
    Refusal,
    RefusalCode,
    RegisteredOperation,
    SourceRef,
    authorize_effect,
    build_decision_packet,
    build_evidence_item,
    candidate_set_digest,
    stable_fingerprint,
)
from aeos_kernel.verification import candidate_eligibility, verify_packet
from tests.factories import (
    NOW,
    AcceptingVerifier,
    FixedClock,
    candidate,
    evidence,
    packet,
    policy,
    subject,
    tamper_packet,
)
from tests.test_effects_and_lifecycle import context, operation


def _decide(selected: Any = None) -> tuple[Any, Any, Any]:
    decision_packet = packet()
    chosen = selected if selected is not None else candidate()
    recommendation = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        decision_packet, (chosen,)
    )
    assert not isinstance(recommendation, Refusal), recommendation
    return decision_packet, chosen, recommendation


def _attestation(decision_packet: Any, recommendation: Any) -> HumanAttestation:
    """The founder's 'use this' for exactly this recommendation — its own decision identity,
    not the default fixture's, so a priced candidate is attested as itself."""
    return HumanAttestation(
        attestation_id="attestation-1",
        actor_id="founder-1",
        capacity="founder",
        decision_id=recommendation.decision_id,
        decision_revision=recommendation.decision_revision,
        recommendation_digest=recommendation.digest,
        subject_digest=decision_packet.subject.content_digest,
        projection_digest=stable_fingerprint({"screen": "article-1"}),
        response=HumanResponse.USE_THIS,
        idempotency_key="effect-key-1",
        decided_at=NOW,
    )


def _authorize(
    decision_packet: Any,
    selected: Any,
    recommendation: Any,
    *,
    current_operation: RegisteredOperation | None = None,
    **context_changes: Any,
) -> Any:
    current_operation = current_operation or operation()
    current: AuthorizationContext = context(decision_packet, recommendation, current_operation)
    if context_changes:
        current = replace(current, **context_changes)
    return authorize_effect(
        packet=decision_packet,
        recommendation=recommendation,
        candidates=(selected,),
        attestation=_attestation(decision_packet, recommendation),
        operation=current_operation,
        context=current,
        idempotency_key="effect-key-1",
        authorized_at=NOW,
    )


def _refused(result: Any, code: RefusalCode, reason: str) -> None:
    assert isinstance(result, Refusal), result
    assert result.code is code, result
    assert result.reason == reason


# ------------------------------------------------------------------ effect authorization


def test_the_unchanged_effect_is_authorized() -> None:
    """The control: every refusal below is one input away from this authorization."""
    assert not isinstance(_authorize(*_decide()), Refusal)


def test_a_packet_that_is_not_the_current_one_is_refused() -> None:
    _refused(
        _authorize(*_decide(), current_packet_digest="b" * 64),
        RefusalCode.STALE_INPUT,
        "packet is not the current canonical packet",
    )


def test_a_recommendation_that_is_not_the_current_record_is_refused() -> None:
    _refused(
        _authorize(*_decide(), current_recommendation_digest="b" * 64),
        RefusalCode.STALE_INPUT,
        "recommendation is not the current exact record",
    )


def test_an_operation_registered_under_another_version_is_not_the_selected_effect() -> None:
    _refused(
        _authorize(*_decide(), current_operation=replace(operation(), operation_version="2")),
        RefusalCode.EFFECT_NOT_REGISTERED,
        "the selected effect is not registered",
    )


def test_a_policy_that_changed_since_the_recommendation_is_refused() -> None:
    _refused(
        _authorize(*_decide(), current_policy_digest="b" * 64),
        RefusalCode.STALE_INPUT,
        "authority, policy, operation or source pins changed",
    )


def test_an_operation_whose_parameter_contract_drifted_is_refused() -> None:
    drifted = replace(operation(), parameter_names=frozenset({"article_id"}))
    _refused(
        _authorize(*_decide(), current_operation=drifted),
        RefusalCode.EFFECT_NOT_REGISTERED,
        "effect parameter contract drifted",
    )


def test_an_operation_whose_result_contract_drifted_is_refused() -> None:
    drifted = replace(operation(), expected_postcondition="something_else_entirely")
    _refused(
        _authorize(*_decide(), current_operation=drifted),
        RefusalCode.EFFECT_NOT_REGISTERED,
        "effect result contract drifted",
    )


def test_an_effect_whose_cost_ceiling_exceeds_the_available_budget_is_refused() -> None:
    priced = candidate()
    priced = replace(priced, effect=replace(priced.effect, cost_ceiling_minor_units=5))
    bound = {"current_candidate_set_digest": candidate_set_digest((priced,))}
    _refused(
        _authorize(*_decide(priced), available_cost_minor_units=4, **bound),
        RefusalCode.EFFECT_PRECONDITION_FAILED,
        "effect cost ceiling exceeds available budget",
    )
    assert not isinstance(
        _authorize(*_decide(priced), available_cost_minor_units=5, **bound), Refusal
    )


# --------------------------------------------------------------------- packet verification


def _packet_with(**changes: Any) -> Any:
    current_policy = changes.pop("policy", policy())
    values: dict[str, Any] = {
        "packet_id": "packet-1",
        "subject": subject(model_allowed=current_policy.permits_model_choice),
        "evidence": (evidence(model_allowed=current_policy.permits_model_choice),),
        "authority_bundle_digest": "c" * 64,
        "policy": current_policy,
        "allowed_actions": ("improve_answer", "improve_description"),
        "source_head_pins": {"wema_git": "76e7c0f4fb1df28a9b77a02e1743eec83cd5a249"},
        "adapter_id": "wema.article",
        "adapter_version": "1",
        "created_at": NOW,
    }
    values.update(changes)
    return build_decision_packet(**values)


def _verify(decision_packet: Any) -> Any:
    return verify_packet(decision_packet, verifier=AcceptingVerifier(), now=NOW)


def test_the_unchanged_packet_verifies() -> None:
    assert _verify(packet()) is None


def test_an_unsupported_schema_version_is_refused_before_anything_else() -> None:
    _refused(
        _verify(tamper_packet(packet(), schema_version="3")),
        RefusalCode.INVALID_PACKET,
        "packet schema version is not supported",
    )


def test_a_subject_not_permitted_for_decision_use_is_refused() -> None:
    _refused(
        _verify(_packet_with(subject=replace(subject(), allowed_uses=("model",)))),
        RefusalCode.INVALID_PACKET,
        "subject is not permitted for decision use",
    )


def test_a_subject_not_permitted_for_model_use_is_refused_when_the_policy_permits_a_model() -> None:
    _refused(
        _verify(
            _packet_with(
                policy=policy(model=True),
                subject=subject(model_allowed=False),
                evidence=(evidence(model_allowed=True),),
            )
        ),
        RefusalCode.INVALID_PACKET,
        "subject is not permitted for model use",
    )


def test_evidence_not_permitted_for_model_use_is_refused_when_the_policy_permits_a_model() -> None:
    _refused(
        _verify(_packet_with(policy=policy(model=True), evidence=(evidence(model_allowed=False),))),
        RefusalCode.INVALID_EVIDENCE,
        "evidence 'e1' is not permitted for model use",
    )


def test_evidence_of_another_subject_revision_is_stale() -> None:
    _refused(
        _verify(_packet_with(evidence=(evidence(revision="0"),))),
        RefusalCode.STALE_INPUT,
        "evidence 'e1' is stale",
    )


def test_evidence_not_permitted_for_decision_use_is_refused() -> None:
    model_only = build_evidence_item(
        evidence_id="e1",
        source_tier="host_state",
        vertical_id="wema",
        tenant_id="wema",
        subject_id="article-1",
        subject_revision="1",
        payload={"needs_attention": ["answer_first"]},
        source_ref=SourceRef("analysis", "e1", "1", "b" * 64),
        observed_at=NOW,
        expires_at=None,
        research_receipt_digest="",
        allowed_uses=("model",),
    )
    _refused(
        _verify(_packet_with(evidence=(model_only,))),
        RefusalCode.INVALID_EVIDENCE,
        "evidence 'e1' is not permitted for decision use",
    )


def test_a_candidate_outside_the_packet_vocabulary_is_ineligible() -> None:
    eligible, reason = candidate_eligibility(candidate(action="delete_everything"), packet())
    assert not eligible
    assert reason == "action 'delete_everything' is outside the packet vocabulary"


def test_a_proof_claiming_a_tier_its_citations_do_not_support_is_ineligible() -> None:
    eligible, reason = candidate_eligibility(candidate(source_tier="canon"), packet())
    assert not eligible
    assert reason == "proof claims an authority tier its citations do not support"


# ------------------------------------------------------------------------- contracts


@pytest.mark.parametrize(
    ("changes", "sentence"),
    [
        ({"allowed_uses": ()}, "subject allowed_uses must be nonempty"),
        ({"allowed_uses": ("decision", "decision")}, "subject allowed_uses must be unique"),
        ({"source_refs": ()}, "subject source_refs must be nonempty"),
        (
            {
                "source_refs": (
                    SourceRef("wema_article", "article-1", "1", "a" * 64),
                    SourceRef("wema_article", "article-1", "1", "a" * 64),
                )
            },
            "subject source references must be unique",
        ),
    ],
)
def test_a_subject_contract_refuses_its_malformed_shapes(
    changes: dict[str, Any], sentence: str
) -> None:
    with pytest.raises(ContractError, match=sentence):
        replace(subject(), **changes)


@pytest.mark.parametrize(
    ("changes", "sentence"),
    [
        ({"allowed_uses": ()}, "evidence allowed_uses must be nonempty"),
        ({"allowed_uses": ("decision", "decision")}, "evidence allowed_uses must be unique"),
    ],
)
def test_an_evidence_contract_refuses_its_malformed_shapes(
    changes: dict[str, Any], sentence: str
) -> None:
    with pytest.raises(ContractError, match=sentence):
        replace(evidence(), **changes)


@pytest.mark.parametrize(
    ("base", "changes", "sentence"),
    [
        (policy(), {"intensity": "loud"}, "decision intensity is not recognized"),
        (
            policy(),
            {"requires_human_attestation": True, "required_capacity": ""},
            "human attestation requires a named capacity",
        ),
        (policy(), {"max_model_calls": -1}, "model budgets must be nonnegative"),
        (
            policy(model=True),
            {"max_model_cost_minor_units": -1},
            "model budgets must be nonnegative",
        ),
        (
            policy(model=True),
            {"level": AuthorityLevel.DETERMINISTIC},
            "model choice requires agent_judgment authority",
        ),
    ],
)
def test_a_policy_contract_refuses_its_malformed_shapes(
    base: Any, changes: dict[str, Any], sentence: str
) -> None:
    with pytest.raises(ContractError, match=sentence):
        replace(base, **changes)


def test_an_effect_template_refuses_a_negative_cost_ceiling() -> None:
    with pytest.raises(ContractError, match="cost ceiling must be nonnegative"):
        replace(candidate().effect, cost_ceiling_minor_units=-1)


def _receipt(**changes: Any) -> EffectReceipt:
    values: dict[str, Any] = {
        "receipt_id": "receipt-1",
        "authorization_id": "authorization-1",
        "decision_id": "decision-1",
        "decision_revision": 1,
        "operation": "wema.article.create_revision",
        "operation_version": "1",
        "request_digest": "a" * 64,
        "status": EffectStatus.APPLIED,
        "applied_at": NOW,
        "result_refs": ("wema_article:article-1:2",),
        "actual_postimage_digest": "b" * 64,
    }
    values.update(changes)
    return EffectReceipt(**values)


def test_the_base_receipt_is_a_valid_contract() -> None:
    assert _receipt().status is EffectStatus.APPLIED


def test_a_receipt_contract_refuses_its_malformed_shapes() -> None:
    not_applied = next(status for status in EffectStatus if status is not EffectStatus.APPLIED)
    with pytest.raises(ContractError, match="decision_revision must be positive"):
        _receipt(decision_revision=0)
    with pytest.raises(ContractError, match="receipt result references must be unique"):
        _receipt(result_refs=("ref", "ref"))
    with pytest.raises(ContractError, match="safe diagnostic exceeds the 2000 character bound"):
        _receipt(status=not_applied, safe_diagnostic="x" * 2001)
    with pytest.raises(ContractError, match="an applied receipt requires durable result evidence"):
        _receipt(result_refs=(), actual_postimage_digest="")
    with pytest.raises(ContractError, match="a non-applied receipt requires a safe diagnostic"):
        _receipt(status=not_applied, safe_diagnostic="")
