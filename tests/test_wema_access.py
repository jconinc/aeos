"""Mailbox access recovery must authorize the promised compound effect (§13.7)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from aeos_kernel import (
    AuthorityLevel,
    AuthorityPolicy,
    AuthorizationContext,
    DecisionEngine,
    DecisionIntensity,
    DecisionStatus,
    EffectReceipt,
    EffectStatus,
    HumanAttestation,
    HumanResponse,
    Refusal,
    RefusalCode,
    RegisteredOperation,
    authorize_effect,
    stable_fingerprint,
    verify_effect_receipt,
)
from aeos_kernel.adapters.wema_mail import (
    WemaMailboxPolicy,
    WemaMailMessageProjection,
    WemaOrderContext,
    build_wema_mail_packet,
    mail_candidates,
)
from tests.factories import NOW, AcceptingVerifier, FixedClock


def mailbox() -> WemaMailboxPolicy:
    return WemaMailboxPolicy(
        mailbox_id="support",
        purpose="support",
        owner="founder",
        response_promise_hours=48,
        allowed_actions=("resend_access_and_reply", "reply_only", "open_mailbox"),
        registry_version="mailboxes@1",
        registry_digest="d" * 64,
    )


def message() -> WemaMailMessageProjection:
    return WemaMailMessageProjection(
        message_id="message-access-1",
        mailbox_id="support",
        classification="delivery_problem",
        risk_flag=False,
        owner="founder",
        recommended_action="resend_access_and_reply",
        fallback_action="reply_only",
        requires=("order_matched",),
        requires_satisfied=("order_matched",),
        template_id="access_resent",
        safe_summary="Cannot find the access link for a fulfilled order.",
        received_at=NOW,
        deadline_at=NOW,
    )


def legacy_order() -> WemaOrderContext:
    return WemaOrderContext(
        order_id="order-access-1",
        status="fulfilled",
        amount_minor=2900,
        currency="USD",
        days_since_purchase=2,
        refundable=True,
    )


@pytest.mark.parametrize("order", [None, legacy_order()], ids=["absent", "unbound-legacy"])
def test_entailed_access_requires_current_native_access_source(
    order: WemaOrderContext | None,
) -> None:
    # A mere registry claim that an order matched cannot authorize a new access delivery.
    with pytest.raises(ValueError, match="current access source"):
        mail_candidates(mailbox(), message(), order)


def test_missing_order_entails_the_existing_reply_fallback() -> None:
    unresolved = replace(message(), requires_satisfied=())
    candidates = mail_candidates(mailbox(), unresolved, None)
    assert [candidate.action for candidate in candidates] == ["reply_only", "open_mailbox"]
    assert candidates[0].proof.claimed_entailed
    assert candidates[0].effect is not None
    assert candidates[0].effect.operation == "wema.mail.send_reply"


def access_order() -> WemaOrderContext:
    return replace(legacy_order(), access_source_digest="e" * 64)


def authorization_inputs(order: WemaOrderContext | None = None) -> dict[str, Any]:
    order = access_order() if order is None else order
    policy = AuthorityPolicy(
        policy_id="wema.mail.reply_with_tap",
        policy_version="2",
        level=AuthorityLevel.STANDARD_DEFAULT,
        intensity=DecisionIntensity.OUTWARD_OR_IRREVERSIBLE,
        allowed_boundary_tags=("outbound_mail", "access_recovery"),
        required_capacity="founder",
        requires_human_attestation=True,
        permits_model_choice=False,
    )
    packet = build_wema_mail_packet(
        tenant_id="wema",
        mailbox=mailbox(),
        message=message(),
        order=order,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_mailbox_registry": "mailboxes@1"},
        policy=policy,
        observed_at=NOW,
    )
    candidates = mail_candidates(mailbox(), message(), order)
    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision=packet.subject.revision), clock=FixedClock()
    ).decide(packet, candidates)
    assert recommendation.status is DecisionStatus.PROPOSED
    assert recommendation.selected_candidate_id == "mail-resend-access-and-reply"
    assert recommendation.model_calls == ()
    operation = RegisteredOperation(
        operation="wema.order.resend_access_and_reply",
        operation_version="1",
        parameter_names=frozenset({"message_id", "order_id", "access_source_digest"}),
        boundary_tags=frozenset({"outbound_mail", "access_recovery"}),
        expected_postcondition="access_link_accepted_for_delivery_and_reply_sent",
        intensity=DecisionIntensity.OUTWARD_OR_IRREVERSIBLE,
        requires_external_confirmation=True,
        fanout_ceiling=2,
    )
    projection_digest = stable_fingerprint({"message_id": message().message_id, "text": "Draft."})
    human = HumanAttestation(
        attestation_id="access-attestation-1",
        actor_id="founder-1",
        capacity="founder",
        decision_id=recommendation.decision_id,
        decision_revision=recommendation.decision_revision,
        recommendation_digest=recommendation.digest,
        subject_digest=packet.subject.content_digest,
        projection_digest=projection_digest,
        response=HumanResponse.USE_THIS,
        idempotency_key="access-request-1",
        decided_at=NOW,
    )
    current = AuthorizationContext(
        current_subject_revision=packet.subject.revision,
        current_subject_digest=packet.subject.content_digest,
        current_packet_digest=packet.packet_digest,
        current_recommendation_digest=recommendation.digest,
        current_candidate_set_digest=recommendation.candidate_set_digest,
        current_projection_digest=projection_digest,
        current_authority_bundle_digest=packet.authority_bundle_digest,
        current_policy_digest=stable_fingerprint(policy.as_dict()),
        current_operation_digest=operation.digest,
        current_source_head_pins=dict(packet.source_head_pins),
        current_adapter_id=packet.adapter_id,
        current_adapter_version=packet.adapter_version,
        verified_actor_id=human.actor_id,
        verified_capacity=human.capacity,
        effects_enabled=True,
        provider_ready=True,
        available_cost_minor_units=0,
    )
    return {
        "packet": packet,
        "recommendation": recommendation,
        "candidates": tuple(sorted(candidates, key=lambda candidate: candidate.candidate_id)),
        "attestation": human,
        "operation": operation,
        "context": current,
        "idempotency_key": human.idempotency_key,
        "authorized_at": NOW,
    }


def test_human_attestation_authorizes_both_access_delivery_and_reply() -> None:
    inputs = authorization_inputs()
    result = authorize_effect(**inputs)
    assert not isinstance(result, Refusal)
    assert result.operation == "wema.order.resend_access_and_reply"
    assert result.parameters == {
        "message_id": message().message_id,
        "order_id": access_order().order_id,
        "access_source_digest": access_order().access_source_digest,
    }
    assert set(result.boundary_tags) == {"outbound_mail", "access_recovery"}
    assert result.expected_postcondition == "access_link_accepted_for_delivery_and_reply_sent"
    selected = next(c for c in inputs["candidates"] if c.proof.claimed_entailed)
    assert "order_context" in selected.proof.cited_evidence_ids
    assert result.attestation_id == inputs["attestation"].attestation_id
    # This validates the adapter/authorizer contract, not an actual provider delivery.
    assert authorize_effect(**inputs) == result


@pytest.mark.parametrize("digest", ["", "e" * 63, "Z" * 64, "a" * 63 + "@"])
def test_access_source_is_a_digest_never_a_capability_or_address(digest: str) -> None:
    with pytest.raises(ValueError, match="access source digest"):
        replace(legacy_order(), access_source_digest=digest)


def test_paid_order_cannot_resend_access_before_fulfillment() -> None:
    paid = replace(access_order(), status="paid")
    with pytest.raises(ValueError, match="fulfilled order"):
        mail_candidates(mailbox(), message(), paid)
    unresolved = replace(message(), requires_satisfied=())
    assert [c.action for c in mail_candidates(mailbox(), unresolved, paid)] == [
        "reply_only",
        "open_mailbox",
    ]


def test_risky_delivery_problem_still_entails_reading_the_mailbox() -> None:
    candidates = mail_candidates(mailbox(), replace(message(), risk_flag=True), access_order())
    assert candidates[0].action == "open_mailbox"
    assert candidates[0].proof.claimed_entailed
    assert candidates[0].effect is None
    assert not any(c.proof.claimed_entailed for c in candidates[1:])


def test_access_source_change_invalidates_the_old_decision() -> None:
    old = authorization_inputs()
    current = authorization_inputs(replace(access_order(), access_source_digest="f" * 64))
    assert old["packet"].subject.content_digest != current["packet"].subject.content_digest
    old["context"] = current["context"]
    result = authorize_effect(**old)
    assert isinstance(result, Refusal)
    assert result.code is RefusalCode.STALE_INPUT


@pytest.mark.parametrize(
    "change",
    [
        {"verified_actor_id": "different-founder"},
        {"verified_capacity": "reader"},
        {"effects_enabled": False},
        {"provider_ready": False},
        {"current_adapter_version": "1"},
    ],
    ids=["wrong-actor", "wrong-role", "effects-paused", "provider-unready", "old-adapter"],
)
def test_resend_uses_the_existing_current_authority_fences(change: dict[str, object]) -> None:
    inputs = authorization_inputs()
    inputs["context"] = replace(inputs["context"], **change)
    assert isinstance(authorize_effect(**inputs), Refusal)


@pytest.mark.parametrize("response", [None, HumanResponse.NOT_NOW, HumanResponse.CHANGE_IT])
def test_resend_needs_the_actual_affirmative_human_attestation(
    response: HumanResponse | None,
) -> None:
    inputs = authorization_inputs()
    inputs["attestation"] = (
        None if response is None else replace(inputs["attestation"], response=response)
    )
    assert isinstance(authorize_effect(**inputs), Refusal)


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("message_id", "other-message"),
        ("order_id", "other-order"),
        ("access_source_digest", "0" * 64),
    ],
)
def test_substituted_access_target_or_source_cannot_use_the_attestation(
    parameter: str,
    value: str,
) -> None:
    inputs = authorization_inputs()
    candidates = []
    for candidate in inputs["candidates"]:
        if candidate.proof.claimed_entailed:
            effect = candidate.effect
            candidate = replace(
                candidate,
                effect=replace(effect, parameters={**effect.parameters, parameter: value}),
            )
        candidates.append(candidate)
    inputs["candidates"] = tuple(candidates)
    result = authorize_effect(**inputs)
    assert isinstance(result, Refusal)
    assert result.code is RefusalCode.CONFLICT


def test_generic_reply_authority_cannot_authorize_access_recovery() -> None:
    inputs = authorization_inputs()
    operation = replace(
        inputs["operation"],
        operation="wema.mail.send_reply",
        parameter_names=frozenset({"message_id"}),
        boundary_tags=frozenset({"outbound_mail"}),
        expected_postcondition="one_reply_sent_to_original_sender",
        fanout_ceiling=1,
    )
    inputs["operation"] = operation
    inputs["context"] = replace(inputs["context"], current_operation_digest=operation.digest)
    result = authorize_effect(**inputs)
    assert isinstance(result, Refusal)
    assert result.code is RefusalCode.EFFECT_NOT_REGISTERED


def test_access_effect_needs_external_confirmation_and_the_compound_operation() -> None:
    inputs = authorization_inputs()
    result = authorize_effect(**inputs)
    assert not isinstance(result, Refusal)
    receipt = EffectReceipt(
        receipt_id="access-receipt-1",
        authorization_id=result.authorization_id,
        decision_id=result.decision_id,
        decision_revision=result.decision_revision,
        operation=result.operation,
        operation_version="1",
        request_digest=result.request_digest,
        status=EffectStatus.APPLIED,
        applied_at=NOW,
        result_refs=("access-attempt-1", "reply-1"),
        actual_postimage_digest="f" * 64,
        external_confirmation_ref="fictional-compound-delivery-receipt-1",
    )
    assert (
        verify_effect_receipt(authorized=result, receipt=receipt, operation=inputs["operation"])
        is None
    )
    for altered in (
        replace(receipt, external_confirmation_ref=""),
        replace(receipt, operation="wema.mail.send_reply"),
    ):
        assert (
            verify_effect_receipt(
                authorized=result,
                receipt=altered,
                operation=inputs["operation"],
            )
            is not None
        )


@pytest.mark.parametrize(
    "change",
    [
        {"owner": "customer"},
        {"recommended_action": "send_access_to_anyone"},
        {"fallback_action": "send_access_to_anyone"},
        {"deadline_at": NOW - timedelta(minutes=1)},
        {"requires_satisfied": ("caller_says_authorized",)},
        {"message_id": " "},
    ],
    ids=["wrong-owner", "unknown-action", "unknown-fallback", "bad-time", "invented-fact", "no-id"],
)
def test_access_routing_refuses_invalid_native_projection(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(message(), **change)


def test_access_action_must_be_enabled_for_this_mailbox() -> None:
    with pytest.raises(ValueError, match="outside the mailbox"):
        mail_candidates(
            replace(mailbox(), allowed_actions=("reply_only", "open_mailbox")),
            message(),
            access_order(),
        )


def test_access_recovery_permission_cannot_be_hidden_under_outbound_mail() -> None:
    inputs = authorization_inputs()
    operation = replace(inputs["operation"], boundary_tags=frozenset({"outbound_mail"}))
    inputs["operation"] = operation
    inputs["context"] = replace(inputs["context"], current_operation_digest=operation.digest)
    assert isinstance(authorize_effect(**inputs), Refusal)


def test_compound_operation_refuses_a_single_recipient_ceiling() -> None:
    inputs = authorization_inputs()
    operation = replace(inputs["operation"], fanout_ceiling=1)
    inputs["operation"] = operation
    inputs["context"] = replace(inputs["context"], current_operation_digest=operation.digest)
    assert isinstance(authorize_effect(**inputs), Refusal)
