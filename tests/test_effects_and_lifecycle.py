from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from aeos_kernel import (
    AuthorizationContext,
    ContractError,
    DecisionEngine,
    DecisionIntensity,
    DecisionRecord,
    DecisionStatus,
    EffectReceipt,
    EffectStatus,
    HumanAttestation,
    HumanResponse,
    Refusal,
    RefusalCode,
    RegisteredOperation,
    authorize_effect,
    candidate_set_digest,
    reopen_record,
    stable_fingerprint,
    transition_record,
    verify_effect_receipt,
)
from tests.factories import NOW, AcceptingVerifier, FixedClock, candidate, packet


def recommendation_and_inputs():  # type: ignore[no-untyped-def]
    decision_packet = packet()
    selected = candidate()
    recommendation = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        decision_packet, (selected,)
    )
    return decision_packet, selected, recommendation


def attestation(
    recommendation_digest: str, *, response: HumanResponse = HumanResponse.USE_THIS
) -> HumanAttestation:
    decision_packet, _selected, recommendation = recommendation_and_inputs()
    return HumanAttestation(
        attestation_id="attestation-1",
        actor_id="founder-1",
        capacity="founder",
        decision_id=recommendation.decision_id,
        decision_revision=recommendation.decision_revision,
        recommendation_digest=recommendation_digest,
        subject_digest=decision_packet.subject.content_digest,
        projection_digest=stable_fingerprint({"screen": "article-1"}),
        response=response,
        idempotency_key="effect-key-1",
        decided_at=NOW,
    )


def operation() -> RegisteredOperation:
    return RegisteredOperation(
        operation="wema.article.create_revision",
        operation_version="1",
        parameter_names=frozenset({"article_id", "expected_digest", "draft"}),
        boundary_tags=frozenset({"content_revision"}),
        expected_postcondition="new_unapproved_article_revision",
        intensity=DecisionIntensity.INTERNAL_EFFECT,
    )


def context(
    decision_packet,
    recommendation,
    current_operation: RegisteredOperation,  # type: ignore[no-untyped-def]
) -> AuthorizationContext:
    return AuthorizationContext(
        current_subject_revision="1",
        current_subject_digest="a" * 64,
        current_packet_digest=decision_packet.packet_digest,
        current_recommendation_digest=recommendation.digest,
        current_candidate_set_digest=candidate_set_digest((candidate(),)),
        current_projection_digest=stable_fingerprint({"screen": "article-1"}),
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


def test_exact_human_attestation_authorizes_registered_internal_effect() -> None:
    decision_packet, selected, recommendation = recommendation_and_inputs()
    current_operation = operation()
    result = authorize_effect(
        packet=decision_packet,
        recommendation=recommendation,
        candidates=(selected,),
        attestation=attestation(recommendation.digest),
        operation=current_operation,
        context=context(decision_packet, recommendation, current_operation),
        idempotency_key="effect-key-1",
        authorized_at=NOW,
    )
    assert not isinstance(result, Refusal)
    assert result.operation == "wema.article.create_revision"
    assert result.attestation_id == "attestation-1"
    assert result.precondition_digest == "a" * 64
    assert result.recommendation_digest == recommendation.digest
    assert result.candidate_set_digest == candidate_set_digest((selected,))
    assert result.operation_contract_digest == current_operation.digest
    assert result.attestation_digest == attestation(recommendation.digest).digest

    receipt = EffectReceipt(
        receipt_id="receipt-1",
        authorization_id=result.authorization_id,
        decision_id=result.decision_id,
        decision_revision=result.decision_revision,
        operation=result.operation,
        operation_version=result.operation_version,
        request_digest=result.request_digest,
        status=EffectStatus.APPLIED,
        applied_at=NOW,
        result_refs=("article-version-2",),
        actual_postimage_digest="f" * 64,
    )
    assert (
        verify_effect_receipt(
            authorized=result,
            receipt=receipt,
            operation=current_operation,
        )
        is None
    )
    wrong = replace(receipt, request_digest="0" * 64)
    refusal = verify_effect_receipt(
        authorized=result,
        receipt=wrong,
        operation=current_operation,
    )
    assert refusal is not None
    assert refusal.code is RefusalCode.EFFECT_RECEIPT_INVALID
    failed_receipt = replace(
        receipt,
        status=EffectStatus.FAILED,
        result_refs=(),
        actual_postimage_digest="",
        safe_diagnostic="provider rejected the operation",
    )
    refusal = verify_effect_receipt(
        authorized=result,
        receipt=failed_receipt,
        operation=current_operation,
    )
    assert refusal is not None
    assert refusal.code is RefusalCode.EFFECT_RECEIPT_INVALID

    outward = replace(
        current_operation,
        intensity=DecisionIntensity.OUTWARD_OR_IRREVERSIBLE,
        requires_external_confirmation=True,
    )
    outward_authorized = replace(result, operation_contract_digest=outward.digest)
    refusal = verify_effect_receipt(
        authorized=outward_authorized,
        receipt=replace(receipt, request_digest=outward_authorized.request_digest),
        operation=outward,
    )
    assert refusal is not None
    assert refusal.code is RefusalCode.EXTERNAL_CONFIRMATION_MISSING


@pytest.mark.parametrize(
    ("human", "expected"),
    [
        (None, RefusalCode.HUMAN_REQUIRED),
        (HumanResponse.CHANGE_IT, RefusalCode.HUMAN_ATTESTATION_INVALID),
        (HumanResponse.NOT_NOW, RefusalCode.HUMAN_ATTESTATION_INVALID),
    ],
)
def test_missing_or_non_use_attestation_never_authorizes_effect(
    human: HumanResponse | None, expected: RefusalCode
) -> None:
    decision_packet, selected, recommendation = recommendation_and_inputs()
    current_operation = operation()
    submitted = None if human is None else attestation(recommendation.digest, response=human)
    result = authorize_effect(
        packet=decision_packet,
        recommendation=recommendation,
        candidates=(selected,),
        attestation=submitted,
        operation=current_operation,
        context=context(decision_packet, recommendation, current_operation),
        idempotency_key="effect-key-1",
        authorized_at=NOW,
    )
    assert isinstance(result, Refusal)
    assert result.code is expected


def test_effect_refuses_when_subject_changes_after_recommendation() -> None:
    decision_packet, selected, recommendation = recommendation_and_inputs()
    current_operation = operation()
    changed = replace(
        context(decision_packet, recommendation, current_operation),
        current_subject_revision="2",
        current_subject_digest="f" * 64,
    )
    result = authorize_effect(
        packet=decision_packet,
        recommendation=recommendation,
        candidates=(selected,),
        attestation=attestation(recommendation.digest),
        operation=current_operation,
        context=changed,
        idempotency_key="effect-key-1",
        authorized_at=NOW,
    )
    assert isinstance(result, Refusal)
    assert result.code is RefusalCode.STALE_INPUT


def initial_record() -> DecisionRecord:
    return DecisionRecord(
        record_id="record-1",
        decision_id="decision-1",
        decision_revision=1,
        event_sequence=1,
        status=DecisionStatus.PROPOSED,
        packet_digest="a" * 64,
        recommendation_digest="b" * 64,
        occurred_at=NOW,
    )


def test_lifecycle_is_compare_and_swap_and_append_only() -> None:
    first = initial_record()
    accepted = transition_record(
        first,
        to_status=DecisionStatus.ACCEPTED,
        occurred_at=NOW + timedelta(seconds=1),
        expected_record_digest=first.digest,
        attestation_id="attestation-1",
    )
    assert accepted.event_sequence == 2
    assert accepted.previous_record_digest == first.digest
    assert first.status is DecisionStatus.PROPOSED
    with pytest.raises(ContractError, match="compare-and-swap"):
        transition_record(
            accepted,
            to_status=DecisionStatus.APPLYING,
            occurred_at=NOW + timedelta(seconds=2),
            expected_record_digest=first.digest,
        )


def test_invalid_lifecycle_jump_is_refused() -> None:
    first = initial_record()
    with pytest.raises(ContractError, match="invalid lifecycle transition"):
        transition_record(
            first,
            to_status=DecisionStatus.APPLIED,
            occurred_at=NOW + timedelta(seconds=1),
            expected_record_digest=first.digest,
        )


def test_only_stale_record_reopens_as_a_new_decision_revision() -> None:
    first = initial_record()
    stale = transition_record(
        first,
        to_status=DecisionStatus.STALE,
        occurred_at=NOW + timedelta(seconds=1),
        expected_record_digest=first.digest,
        reason="subject_changed",
    )
    reopened = reopen_record(
        stale,
        packet_digest="c" * 64,
        recommendation_digest="d" * 64,
        occurred_at=NOW + timedelta(seconds=2),
        drift_reason="subject_changed",
    )
    assert reopened.decision_revision == 2
    assert reopened.event_sequence == 1
    assert reopened.status is DecisionStatus.PROPOSED
    assert reopened.previous_record_digest == stale.digest


def test_effect_lifecycle_requires_and_preserves_receipt_evidence() -> None:
    accepted = transition_record(
        initial_record(),
        to_status=DecisionStatus.ACCEPTED,
        occurred_at=NOW + timedelta(seconds=1),
        expected_record_digest=initial_record().digest,
        attestation_id="attestation-1",
    )
    applying = transition_record(
        accepted,
        to_status=DecisionStatus.APPLYING,
        occurred_at=NOW + timedelta(seconds=2),
        expected_record_digest=accepted.digest,
    )
    with pytest.raises(ContractError, match="requires an effect receipt"):
        transition_record(
            applying,
            to_status=DecisionStatus.APPLIED,
            occurred_at=NOW + timedelta(seconds=3),
            expected_record_digest=applying.digest,
        )
    applied = transition_record(
        applying,
        to_status=DecisionStatus.APPLIED,
        occurred_at=NOW + timedelta(seconds=3),
        expected_record_digest=applying.digest,
        effect_receipt_id="receipt-1",
    )
    closed = transition_record(
        applied,
        to_status=DecisionStatus.VERIFIED_CLOSED,
        occurred_at=NOW + timedelta(seconds=4),
        expected_record_digest=applied.digest,
        outcome_evidence_ids=("outcome-1",),
    )
    assert closed.attestation_id == "attestation-1"
    assert closed.effect_receipt_id == "receipt-1"
    assert closed.outcome_evidence_ids == ("outcome-1",)
    with pytest.raises(ContractError, match="time must advance"):
        transition_record(
            applied,
            to_status=DecisionStatus.VERIFIED_CLOSED,
            occurred_at=applied.occurred_at,
            expected_record_digest=applied.digest,
        )


def test_reopen_requires_material_change() -> None:
    first = initial_record()
    stale = transition_record(
        first,
        to_status=DecisionStatus.STALE,
        occurred_at=NOW + timedelta(seconds=1),
        expected_record_digest=first.digest,
        reason="subject_changed",
    )
    with pytest.raises(ContractError, match="material decision input change"):
        reopen_record(
            stale,
            packet_digest=stale.packet_digest,
            recommendation_digest=stale.recommendation_digest,
            occurred_at=NOW + timedelta(seconds=2),
            drift_reason="subject_changed",
        )
