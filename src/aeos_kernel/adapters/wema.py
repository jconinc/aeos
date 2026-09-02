"""Wema article-decision v1 interchange mappings.

The adapter consumes safe projections; it never imports Wema ORM, API, Desk, or provider
code. Wema remains responsible for producing these fields and for validating the proposed
draft through its existing ``ArticleDraft`` contract before creating a revision.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, EffectTemplate, EntailmentProof, Recommendation
from aeos_kernel.evidence import (
    AuthorityPolicy,
    DecisionPacket,
    DecisionSubject,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
)

ADAPTER_ID = "wema.article"
ADAPTER_VERSION = "2"
ARTICLE_REVISION_OPERATION = "wema.article.create_revision"
ARTICLE_SOURCE_REF_TYPE = "content_article"
ARTICLE_DECISION_KIND = "aeos_article_revision"


@dataclass(frozen=True, slots=True)
class WemaArticleProjection:
    article_id: str
    version_id: str
    version: int
    digest: str
    status: str
    artifact_status: str
    title: str
    question: str
    answer_first: str
    meta_description: str
    article_class: str
    quality_ready: bool
    needs_attention: tuple[str, ...]
    word_count: int
    reading_grade: float | None
    required_reviews: tuple[str, ...]
    approved_reviews: tuple[str, ...]

    def safe_payload(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "version": self.version,
            "status": self.status,
            "artifact_status": self.artifact_status,
            "title": self.title,
            "question": self.question,
            "answer_first": self.answer_first,
            "meta_description": self.meta_description,
            "article_class": self.article_class,
            "quality": {
                "ready": self.quality_ready,
                "needs_attention": list(self.needs_attention),
                "word_count": self.word_count,
                "reading_grade": self.reading_grade,
            },
            "reviews": {
                "required": list(self.required_reviews),
                "approved": list(self.approved_reviews),
            },
        }


def build_wema_article_packet(
    *,
    tenant_id: str,
    article: WemaArticleProjection,
    analysis: Mapping[str, Any],
    aggregate_outcomes: Mapping[str, Any],
    canon_guidance: Mapping[str, Any],
    authority_bundle_digest: str,
    source_head_pins: Mapping[str, str],
    allowed_actions: tuple[str, ...],
    policy: AuthorityPolicy,
    observed_at: datetime,
) -> DecisionPacket:
    source_ref = SourceRef(
        source_type="wema_content_version",
        source_id=article.version_id,
        revision=str(article.version),
        digest=article.digest,
    )
    subject = DecisionSubject(
        vertical_id="wema",
        tenant_id=tenant_id,
        subject_id=article.article_id,
        subject_kind="article_revision",
        revision=str(article.version),
        content_digest=article.digest,
        attributes={
            "status": article.status,
            "artifact_status": article.artifact_status,
            "article_class": article.article_class,
        },
        source_refs=(source_ref,),
        allowed_uses=("decision", "model") if policy.permits_model_choice else ("decision",),
    )
    evidence_payloads = (
        ("article_projection", "host_state", article.safe_payload(), source_ref),
        (
            "article_analysis",
            "host_state",
            dict(analysis),
            SourceRef(
                source_type="wema_article_analysis",
                source_id=article.version_id,
                revision=str(article.version),
                digest=stable_fingerprint(dict(analysis)),
            ),
        ),
        (
            "article_outcomes",
            "observation",
            dict(aggregate_outcomes),
            SourceRef(
                source_type="wema_aggregate_outcomes",
                source_id=article.article_id,
                revision=str(article.version),
                digest=stable_fingerprint(dict(aggregate_outcomes)),
            ),
        ),
        (
            "wema_canon_guidance",
            "canon",
            dict(canon_guidance),
            SourceRef(
                source_type="wema_canon_bundle",
                source_id="wema",
                revision="1",
                digest=stable_fingerprint(dict(canon_guidance)),
            ),
        ),
    )
    evidence = tuple(
        build_evidence_item(
            evidence_id=evidence_id,
            source_tier=source_tier,
            vertical_id=subject.vertical_id,
            tenant_id=subject.tenant_id,
            subject_id=subject.subject_id,
            subject_revision=subject.revision,
            payload=payload,
            source_ref=ref,
            observed_at=observed_at,
            allowed_uses=("decision", "model") if policy.permits_model_choice else ("decision",),
        )
        for evidence_id, source_tier, payload, ref in evidence_payloads
    )
    return build_decision_packet(
        packet_id="wema_article_packet_"
        + stable_fingerprint(
            {"article_id": article.article_id, "version": article.version, "digest": article.digest}
        )[:24],
        subject=subject,
        evidence=evidence,
        authority_bundle_digest=authority_bundle_digest,
        policy=policy,
        allowed_actions=allowed_actions,
        source_head_pins=dict(source_head_pins),
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        created_at=observed_at,
    )


def prepared_revision_candidate(
    *,
    candidate_id: str,
    action: str,
    title: str,
    explanation: str,
    expected_benefit: str,
    evidence_ids: tuple[str, ...],
    source_tier: str,
    article_id: str,
    expected_digest: str,
    prepared_draft: Mapping[str, Any],
    claimed_entailed: bool = False,
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        action=action,
        title=title,
        explanation=explanation,
        expected_benefit=expected_benefit,
        proof=EntailmentProof(
            source_tier=source_tier,
            cited_evidence_ids=evidence_ids,
            reason=explanation,
            claimed_entailed=claimed_entailed,
        ),
        effect=EffectTemplate(
            operation=ARTICLE_REVISION_OPERATION,
            operation_version="1",
            parameters={
                "article_id": article_id,
                "expected_digest": expected_digest,
                "draft": dict(prepared_draft),
            },
            boundary_tags=("content_revision",),
            expected_postcondition="new_unapproved_article_revision",
            reversible=True,
            compensation_ref="restoreArticleRevision",
        ),
    )


def to_owned_action_values(
    recommendation: Recommendation,
    *,
    packet: DecisionPacket,
    candidate: Candidate,
) -> dict[str, Any]:
    """Project one recommendation into Wema's existing ``OwnedAction`` columns."""

    return {
        "module": "marketing",
        "title": candidate.title[:200],
        "body": recommendation.explanation,
        "evidence": {
            "aeos_decision_id": recommendation.decision_id,
            "aeos_decision_revision": recommendation.decision_revision,
            "recommendation_digest": recommendation.digest,
            "packet_digest": packet.packet_digest,
            "article_digest": packet.subject.content_digest,
        },
        "effort": "5min",
        "impact_label": "reputation",
        "rank_class": "compounding",
        "requires_founder_judgment": True,
        "source_ref_type": ARTICLE_SOURCE_REF_TYPE,
        "source_ref_id": packet.subject.subject_id,
        "decision_kind": ARTICLE_DECISION_KIND,
    }
