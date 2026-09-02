from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from aeos_kernel import (
    AuthorityLevel,
    AuthorityPolicy,
    Candidate,
    DecisionIntensity,
    DecisionPacket,
    DecisionSubject,
    EffectTemplate,
    EntailmentProof,
    EvidenceItem,
    ModelCallIdentity,
    ModelDecision,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
    stable_fingerprint,
)
from aeos_kernel.ports import ModelChoiceRequest

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class AcceptingVerifier:
    def __init__(self, *, revision: str = "1") -> None:
        self.revision = revision
        self.authority_valid = True
        self.source_heads_valid = True
        self.research_valid = True

    def verify_authority_bundle(self, digest: str) -> bool:
        return self.authority_valid and digest == "c" * 64

    def verify_source_heads(self, source_head_pins: dict[str, str]) -> bool:
        return self.source_heads_valid and bool(source_head_pins)

    def current_subject_revision(self, subject: DecisionSubject) -> str | None:
        return self.revision

    def verify_research_receipt(self, evidence: EvidenceItem) -> bool:
        return self.research_valid and bool(evidence.research_receipt_digest)


class ScriptedModel:
    def __init__(self, candidate_ids: list[str], *, citations: tuple[str, ...] = ("e1",)) -> None:
        self.candidate_ids = candidate_ids
        self.citations = citations
        self.requests: list[ModelChoiceRequest] = []

    def choose(self, request: ModelChoiceRequest) -> ModelDecision:
        self.requests.append(request)
        candidate_id = self.candidate_ids[len(self.requests) - 1]
        return ModelDecision(
            candidate_id=candidate_id,
            rationale="This choice best matches the cited current evidence.",
            citations=self.citations,
            confidence=0.9,
            identity=ModelCallIdentity(
                provider=request.provider,
                model_id=request.model_id,
                prompt_digest=request.prompt_digest,
                generation_parameters_digest=request.generation_parameters_digest,
                context_classification=request.context_classification,
                attempt=request.attempt,
                cost_minor_units=1,
                input_tokens=10,
                output_tokens=5,
            ),
            retained_output={"candidate_id": candidate_id, "citations": list(self.citations)},
        )


def policy(
    *,
    model: bool = False,
    human: bool = True,
    intensity: DecisionIntensity = DecisionIntensity.INTERNAL_EFFECT,
) -> AuthorityPolicy:
    return AuthorityPolicy(
        policy_id="article_improvement",
        policy_version="1",
        level=AuthorityLevel.AGENT_JUDGMENT if model else AuthorityLevel.DETERMINISTIC,
        intensity=intensity,
        allowed_boundary_tags=("content_revision",),
        required_capacity="founder" if human else "",
        requires_human_attestation=human,
        permits_model_choice=model,
        max_model_calls=2 if model else 0,
        max_model_cost_minor_units=5 if model else 0,
        model_provider="test-provider" if model else "",
        model_id="test-model" if model else "",
        model_context_classification="internal-safe" if model else "",
        model_generation_parameters_digest=stable_fingerprint({"temperature": 0})
        if model
        else "",
    )


def subject(
    *, revision: str = "1", tenant_id: str = "wema", model_allowed: bool = False
) -> DecisionSubject:
    return DecisionSubject(
        vertical_id="wema",
        tenant_id=tenant_id,
        subject_id="article-1",
        subject_kind="article_revision",
        revision=revision,
        content_digest="a" * 64,
        attributes={"status": "draft"},
        source_refs=(SourceRef("wema_article", "article-1", revision, "a" * 64),),
        allowed_uses=("decision", "model") if model_allowed else ("decision",),
    )


def evidence(
    *,
    evidence_id: str = "e1",
    source_tier: str = "host_state",
    tenant_id: str = "wema",
    revision: str = "1",
    expires_at: datetime | None = None,
    research_receipt_digest: str = "",
    model_allowed: bool = False,
) -> EvidenceItem:
    return build_evidence_item(
        evidence_id=evidence_id,
        source_tier=source_tier,
        vertical_id="wema",
        tenant_id=tenant_id,
        subject_id="article-1",
        subject_revision=revision,
        payload={"needs_attention": ["answer_first"]},
        source_ref=SourceRef("analysis", evidence_id, revision, "b" * 64),
        observed_at=NOW,
        expires_at=expires_at,
        research_receipt_digest=research_receipt_digest,
        allowed_uses=("decision", "model") if model_allowed else ("decision",),
    )


def packet(
    *,
    items: tuple[EvidenceItem, ...] | None = None,
    authority_policy: AuthorityPolicy | None = None,
    revision: str = "1",
) -> DecisionPacket:
    current_policy = authority_policy or policy()
    return build_decision_packet(
        packet_id="packet-1",
        subject=subject(revision=revision, model_allowed=current_policy.permits_model_choice),
        evidence=items
        if items is not None
        else (
            evidence(
                revision=revision,
                model_allowed=current_policy.permits_model_choice,
            ),
        ),
        authority_bundle_digest="c" * 64,
        policy=current_policy,
        allowed_actions=("improve_answer", "improve_description"),
        source_head_pins={"wema_git": "76e7c0f4fb1df28a9b77a02e1743eec83cd5a249"},
        adapter_id="wema.article",
        adapter_version="1",
        created_at=NOW,
    )


def candidate(
    candidate_id: str = "candidate-1",
    *,
    action: str = "improve_answer",
    evidence_ids: tuple[str, ...] = ("e1",),
    source_tier: str = "host_state",
    entailed: bool = True,
    boundary_tags: tuple[str, ...] = ("content_revision",),
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        action=action,
        title="Strengthen the opening answer",
        explanation="The opening does not yet answer the caregiver's question directly.",
        proof=EntailmentProof(
            source_tier=source_tier,
            cited_evidence_ids=evidence_ids,
            reason="The registered quality check names this exact gap.",
            claimed_entailed=entailed,
        ),
        expected_benefit="A visitor gets a useful answer sooner.",
        effect=EffectTemplate(
            operation="wema.article.create_revision",
            operation_version="1",
            parameters={
                "article_id": "article-1",
                "expected_digest": "a" * 64,
                "draft": {"title": "A practical answer"},
            },
            boundary_tags=boundary_tags,
            expected_postcondition="new_unapproved_article_revision",
            reversible=True,
            compensation_ref="restoreArticleRevision",
        ),
    )


def tamper_packet(value: DecisionPacket, **changes: object) -> DecisionPacket:
    return replace(value, **changes)
