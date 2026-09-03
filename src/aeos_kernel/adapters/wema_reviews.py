"""Wema deployment-review advisory interchange mappings.

The public checklist is an evidence intake, never an approval surface.  Its bounded notes are
internal evidence for the host, but model use is deliberately forbidden: a public text field
cannot become instructions to a model or an effect.  AEOS decides only whether the registered
operator follow-up is entailed by the closed choices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, EntailmentProof, Recommendation
from aeos_kernel.evidence import (
    AuthorityPolicy,
    DecisionPacket,
    DecisionSubject,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
)
from aeos_kernel.vocabulary import PrivacyClass

REVIEW_ADAPTER_ID = "wema.review"
REVIEW_ADAPTER_VERSION = "1"
REVIEW_DECISION_KIND = "aeos_review_follow_up"
REVIEW_SOURCE_REF_TYPE = "review_submission"
REVIEW_FOLLOW_UP_ACTION = "prepare_review_follow_up"

_DECISIONS = frozenset({"assumed_okay", "looks_good", "needs_change", "not_sure"})


@dataclass(frozen=True, slots=True)
class WemaReviewResponse:
    item_id: str
    decision: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.item_id.strip() or len(self.item_id) > 160:
            raise ValueError("review item ID must contain 1 to 160 characters")
        if self.decision not in _DECISIONS:
            raise ValueError("review decision is not registered")
        if len(self.note) > 280:
            raise ValueError("review note must contain at most 280 characters")

    def as_dict(self) -> dict[str, str]:
        return {"item_id": self.item_id, "decision": self.decision, "note": self.note}


@dataclass(frozen=True, slots=True)
class WemaReviewProjection:
    submission_id: str
    packet_kind: str
    release: str
    inventory_digest: str
    payload_digest: str
    responses: tuple[WemaReviewResponse, ...]

    def __post_init__(self) -> None:
        if self.packet_kind not in {"site", "content", "articles"}:
            raise ValueError("review packet kind is not registered")
        if not self.submission_id.strip() or not self.release.strip():
            raise ValueError("review submission and release identities are required")
        if not 1 <= len(self.responses) <= 100:
            raise ValueError("review projection must contain 1 to 100 responses")
        item_ids = [response.item_id for response in self.responses]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("review response item IDs must be unique")
        for value, label in (
            (self.inventory_digest, "inventory digest"),
            (self.payload_digest, "payload digest"),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"review {label} must be a SHA-256 digest")

    @property
    def attention_count(self) -> int:
        return sum(response.decision in {"needs_change", "not_sure"} for response in self.responses)

    def safe_payload(self) -> dict[str, Any]:
        return {
            "packet_kind": self.packet_kind,
            "release": self.release,
            "inventory_digest": self.inventory_digest,
            "responses": [response.as_dict() for response in self.responses],
            "attention_count": self.attention_count,
        }


def build_wema_review_packet(
    *,
    tenant_id: str,
    review: WemaReviewProjection,
    authority_bundle_digest: str,
    source_head_pins: dict[str, str],
    policy: AuthorityPolicy,
    observed_at: datetime,
) -> DecisionPacket:
    """Build a decision-only packet; public notes are never eligible for model use."""

    source_ref = SourceRef(
        source_type="wema_review_submission",
        source_id=review.submission_id,
        revision=review.payload_digest,
        digest=review.payload_digest,
    )
    subject = DecisionSubject(
        vertical_id="wema",
        tenant_id=tenant_id,
        subject_id=review.submission_id,
        subject_kind="deployment_review",
        revision=review.payload_digest,
        content_digest=review.payload_digest,
        attributes={
            "packet_kind": review.packet_kind,
            "release": review.release,
            "attention_count": review.attention_count,
        },
        source_refs=(source_ref,),
        privacy_classification=PrivacyClass.INTERNAL,
        allowed_uses=("decision",),
    )
    evidence = build_evidence_item(
        evidence_id="review_projection",
        source_tier="host_state",
        vertical_id=subject.vertical_id,
        tenant_id=subject.tenant_id,
        subject_id=subject.subject_id,
        subject_revision=subject.revision,
        payload=review.safe_payload(),
        source_ref=source_ref,
        observed_at=observed_at,
        privacy_classification=PrivacyClass.INTERNAL,
        allowed_uses=("decision",),
    )
    return build_decision_packet(
        packet_id="wema_review_packet_" + stable_fingerprint(review.safe_payload())[:24],
        subject=subject,
        evidence=(evidence,),
        authority_bundle_digest=authority_bundle_digest,
        policy=policy,
        allowed_actions=(REVIEW_FOLLOW_UP_ACTION,),
        source_head_pins=source_head_pins,
        adapter_id=REVIEW_ADAPTER_ID,
        adapter_version=REVIEW_ADAPTER_VERSION,
        created_at=observed_at,
    )


def review_follow_up_candidate(review: WemaReviewProjection) -> Candidate:
    if review.attention_count == 0:
        raise ValueError("an all-clear review does not entail follow-up work")
    return Candidate(
        candidate_id="read-saved-review",
        action=REVIEW_FOLLOW_UP_ACTION,
        title="Read the saved website review",
        explanation=(
            "A release-bound review has changes or questions. Read the saved responses, "
            "prepare the smallest corrections, and return only changed items for another look."
        ),
        expected_benefit=(
            "The reviewer sees focused corrections without repeating the whole review."
        ),
        proof=EntailmentProof(
            source_tier="host_state",
            cited_evidence_ids=("review_projection",),
            reason="At least one closed review choice asks for a change or says it is not clear.",
            claimed_entailed=True,
        ),
    )


def to_review_owned_action_values(
    recommendation: Recommendation,
    *,
    packet: DecisionPacket,
    candidate: Candidate,
) -> dict[str, Any]:
    """Project the advice to Wema's existing operator queue without copying review text."""

    return {
        "module": "review",
        "title": candidate.title[:200],
        "body": recommendation.explanation,
        "evidence": {
            "review_submission_id": packet.subject.subject_id,
            "payload_digest": packet.subject.content_digest,
            "release": packet.subject.attributes["release"],
            "packet_kind": packet.subject.attributes["packet_kind"],
            "attention_count": packet.subject.attributes["attention_count"],
            "aeos_decision_id": recommendation.decision_id,
            "aeos_decision_revision": recommendation.decision_revision,
            "recommendation_digest": recommendation.digest,
            "packet_digest": packet.packet_digest,
        },
        "effort": "30min",
        "impact_label": "reputation",
        "rank_class": "compounding",
        "requires_founder_judgment": False,
        "source_ref_type": REVIEW_SOURCE_REF_TYPE,
        "source_ref_id": packet.subject.subject_id,
        "decision_kind": REVIEW_DECISION_KIND,
    }
