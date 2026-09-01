from __future__ import annotations

from datetime import timedelta

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from aeos_kernel import (
    DecisionEngine,
    EffectReceipt,
    EffectStatus,
    HumanAttestation,
    HumanResponse,
    OutcomeEvidence,
    OutcomeStatus,
    stable_fingerprint,
)
from aeos_kernel.schemas import load_schema
from tests.factories import NOW, AcceptingVerifier, FixedClock, candidate, packet


def validator(definition: str) -> Draft202012Validator:
    bundle = load_schema("bundle.schema.json")
    schema = {"$ref": f"#/$defs/{definition}", "$defs": bundle["$defs"]}
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_packet_candidate_and_recommendation_match_published_v1_schemas() -> None:
    decision_packet = packet()
    selected = candidate()
    recommendation = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        decision_packet, (selected,)
    )
    validator("DecisionPacket").validate(decision_packet.as_dict())
    validator("Candidate").validate(selected.as_dict())
    validator("Recommendation").validate(recommendation.as_dict())


def test_unknown_interchange_field_is_rejected() -> None:
    payload = packet().as_dict()
    payload["surprise"] = "must not be silently accepted"
    with pytest.raises(ValidationError, match="Additional properties"):
        validator("DecisionPacket").validate(payload)


def test_attestation_receipt_and_outcome_match_published_schemas() -> None:
    decision_packet = packet()
    recommendation = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        decision_packet, (candidate(),)
    )
    human = HumanAttestation(
        attestation_id="attestation-1",
        actor_id="founder-1",
        capacity="founder",
        decision_id=recommendation.decision_id,
        decision_revision=1,
        recommendation_digest=recommendation.digest,
        subject_digest=decision_packet.subject.content_digest,
        projection_digest=stable_fingerprint({"projection": "one"}),
        response=HumanResponse.USE_THIS,
        idempotency_key="key-1",
        decided_at=NOW,
    )
    receipt = EffectReceipt(
        receipt_id="receipt-1",
        authorization_id="authorization-1",
        decision_id=recommendation.decision_id,
        decision_revision=1,
        operation="wema.article.create_revision",
        request_digest="f" * 64,
        status=EffectStatus.APPLIED,
        applied_at=NOW,
        result_refs=("version-2",),
        actual_postimage_digest="e" * 64,
    )
    outcome = OutcomeEvidence(
        outcome_id="outcome-1",
        receipt_id=receipt.receipt_id,
        metric_id="article_usefulness_window",
        status=OutcomeStatus.INSUFFICIENT_EVIDENCE,
        window_started_at=NOW,
        window_ended_at=NOW + timedelta(days=7),
        observed_at=NOW + timedelta(days=7),
        aggregate={"reason": "analytics mode does not yet supply this measure"},
        policy_digest="d" * 64,
        evidence_digest="c" * 64,
    )
    validator("HumanAttestation").validate(human.as_dict())
    validator("EffectReceipt").validate(receipt.as_dict())
    validator("OutcomeEvidence").validate(outcome.as_dict())


def test_all_named_entry_schemas_are_published() -> None:
    for name in (
        "decision-packet.schema.json",
        "candidate.schema.json",
        "recommendation.schema.json",
        "human-attestation.schema.json",
        "authorized-effect.schema.json",
        "effect-receipt.schema.json",
        "outcome-evidence.schema.json",
    ):
        assert load_schema(name)["$ref"].startswith("bundle.schema.json#/$defs/")
