"""Operational release: malformed retained state must not become reusable authority."""

from copy import copy, deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from aeos_kernel import AuthorityLevel, ContractError, EffectReceipt, EffectStatus
from aeos_kernel._validation import freeze_json, immutable_json_object, required, utc
from aeos_kernel.adapters.wema_reviews import WemaReviewResponse
from tests.factories import NOW, evidence, packet, policy, subject
from tests.test_adapters import review
from tests.test_graph import snapshot


@pytest.mark.parametrize("changes", [
    {"allowed_uses": ()}, {"allowed_uses": ("decision", "decision")},
    {"source_refs": ()}, {"source_refs": subject().source_refs * 2},
    {"attributes": {"bad": object()}},
])
def test_retained_subject_requires_unique_permissions_and_provenance(changes):
    with pytest.raises(ContractError):
        replace(subject(), **changes)


@pytest.mark.parametrize("changes", [
    {"allowed_uses": ()}, {"allowed_uses": ("decision", "decision")},
    {"observed_at": NOW.replace(tzinfo=None)}, {"payload": {"bad": float("nan")}},
])
def test_retained_evidence_requires_an_explicit_clock_and_strict_payload(changes):
    with pytest.raises(ContractError):
        replace(evidence(), **changes)


@pytest.mark.parametrize("changes", [
    {"intensity": "internal_effect"}, {"allowed_boundary_tags": ("same", "same")},
    {"required_capacity": ""}, {"max_model_calls": -1},
    {"max_model_cost_minor_units": -1},
    {"level": AuthorityLevel.HUMAN_REQUIRED, "requires_human_attestation": False},
])
def test_policy_cannot_encode_an_ambiguous_or_unbounded_authority(changes):
    with pytest.raises(ContractError):
        replace(policy(), **changes)


@pytest.mark.parametrize("changes", [
    {"level": AuthorityLevel.DETERMINISTIC}, {"max_model_calls": 0},
    {"model_provider": ""}, {"model_id": ""}, {"model_context_classification": ""},
])
def test_model_authority_requires_its_complete_exact_call_identity(changes):
    with pytest.raises(ContractError):
        replace(policy(model=True), **changes)


@pytest.mark.parametrize("changes", [
    {"allowed_actions": ()}, {"allowed_actions": ("same", "same")},
    {"source_head_pins": {}}, {"source_head_pins": {"source": ""}},
])
def test_a_retry_packet_cannot_lose_its_action_set_or_source_binding(changes):
    with pytest.raises(ContractError):
        replace(packet(), **changes)


@pytest.mark.parametrize("changes", [
    {"schema_version": "2"}, {"generation": 0}, {"nodes": ()},
    {"nodes": snapshot().nodes * 2}, {"edges": snapshot().edges * 2},
    {"source_head_pins": {}},
])
def test_rebuilt_graph_refuses_unsupported_duplicate_or_unbound_state(changes):
    with pytest.raises(ContractError):
        replace(snapshot(), **changes)


@pytest.mark.parametrize("changes", [
    {"item_id": ""}, {"item_id": "x" * 161}, {"decision": "approved"}, {"note": "x" * 281},
])
def test_public_review_input_cannot_be_an_approval_or_unbounded_text(changes):
    with pytest.raises(ValueError):
        WemaReviewResponse(**{"item_id": "one", "decision": "looks_good", **changes})


@pytest.mark.parametrize("changes", [
    {"packet_kind": "approval"}, {"submission_id": ""}, {"release": ""},
    {"responses": ()}, {"responses": review().responses * 2},
    {"inventory_digest": "unbound"}, {"payload_digest": "g" * 64},
])
def test_review_retry_must_keep_release_inventory_and_unique_response_bindings(changes):
    with pytest.raises(ValueError):
        replace(review(), **changes)


def receipt(**changes):
    return EffectReceipt(**{
        "receipt_id": "receipt-one", "authorization_id": "authorization-one",
        "decision_id": "decision-one", "decision_revision": 1, "operation": "registered",
        "operation_version": "1", "request_digest": "a" * 64, "status": EffectStatus.APPLIED,
        "applied_at": NOW, "result_refs": ("result-one",), **changes,
    })


@pytest.mark.parametrize("changes", [
    {"decision_revision": 0}, {"result_refs": ("result-one", "result-one")},
    {"safe_diagnostic": "x" * 2001}, {"result_refs": ()},
    {"status": EffectStatus.FAILED}, {"external_confirmation_ref": " bad "},
])
def test_completion_receipt_requires_durable_unique_evidence_or_a_safe_failure(changes):
    with pytest.raises(ContractError):
        receipt(**changes)


def test_an_applied_receipt_can_be_bound_to_a_confirmed_postimage_instead_of_a_row():
    confirmed = receipt(result_refs=(), actual_postimage_digest="b" * 64,
                        external_confirmation_ref="provider-receipt")
    assert confirmed.as_dict()["actual_postimage_digest"] == "b" * 64
    assert confirmed.digest


def test_retained_json_copies_remain_deeply_immutable():
    retained = immutable_json_object({"items": [{"value": 1}]}, "retained")
    assert freeze_json(retained) is retained
    assert copy(retained) is retained and deepcopy(retained) is retained
    items = retained["items"]
    assert copy(items) is items and deepcopy(items) is items
    with pytest.raises(TypeError, match="immutable"):
        items.append("new")
    with pytest.raises(TypeError, match="immutable"):
        items[0]["value"] = 2


def test_clock_and_control_characters_are_not_normalized_into_valid_identity():
    with pytest.raises(ContractError, match="control"):
        required("one\x00two", "identity")
    with pytest.raises(ContractError, match="timezone"):
        utc((NOW + timedelta(days=1)).replace(tzinfo=None), "clock")
