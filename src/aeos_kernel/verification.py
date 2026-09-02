"""Fail-closed packet and candidate verification."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from aeos_kernel.decision import Candidate
from aeos_kernel.errors import Refusal, RefusalCode
from aeos_kernel.evidence import DecisionPacket, EvidenceItem
from aeos_kernel.ports import TrustVerifier
from aeos_kernel.vocabulary import DecisionIntensity, PrivacyClass

SOURCE_TIERS: tuple[str, ...] = (
    "legal",
    "product_policy",
    "requirement",
    "host_state",
    "graph",
    "canon",
    "standard",
    "research",
    "observation",
)
ENTAILING_TIERS = frozenset(SOURCE_TIERS[:7])
_TIER_RANK = {tier: rank for rank, tier in enumerate(SOURCE_TIERS)}


def verify_packet(
    packet: DecisionPacket, *, verifier: TrustVerifier, now: datetime
) -> Refusal | None:
    if packet.schema_version not in {"1", "2"}:
        return Refusal(RefusalCode.INVALID_PACKET, "packet schema version is not supported")
    if not packet.has_canonical_digest():
        return Refusal(RefusalCode.INVALID_PACKET, "packet digest is not canonical")
    if (
        packet.subject.privacy_classification is PrivacyClass.PROHIBITED
        or "decision" not in packet.subject.allowed_uses
    ):
        return Refusal(
            RefusalCode.INVALID_PACKET,
            "subject is not permitted for decision use",
        )
    if packet.policy.permits_model_choice and "model" not in packet.subject.allowed_uses:
        return Refusal(RefusalCode.INVALID_PACKET, "subject is not permitted for model use")
    if not verifier.verify_authority_bundle(packet.authority_bundle_digest):
        return Refusal(RefusalCode.AUTHORITY_MISSING, "authority bundle could not be verified")
    if not verifier.verify_source_heads(packet.source_head_pins):
        return Refusal(RefusalCode.STALE_INPUT, "source-head pins are stale or unknown")
    current_revision = verifier.current_subject_revision(packet.subject)
    if current_revision is None or current_revision != packet.subject.revision:
        return Refusal(RefusalCode.STALE_INPUT, "subject revision is not current")
    ids = [item.evidence_id for item in packet.evidence]
    if len(ids) != len(set(ids)):
        return Refusal(RefusalCode.INVALID_EVIDENCE, "evidence identities are not unique")
    for item in packet.evidence:
        refusal = _verify_evidence(item, packet=packet, verifier=verifier, now=now)
        if refusal is not None:
            return refusal
    return None


def _verify_evidence(
    item: EvidenceItem, *, packet: DecisionPacket, verifier: TrustVerifier, now: datetime
) -> Refusal | None:
    if not item.has_canonical_digest():
        return Refusal(
            RefusalCode.INVALID_EVIDENCE, f"evidence {item.evidence_id!r} digest is invalid"
        )
    subject = packet.subject
    if (
        item.vertical_id != subject.vertical_id
        or item.tenant_id != subject.tenant_id
        or item.subject_id != subject.subject_id
    ):
        return Refusal(
            RefusalCode.CROSS_SCOPE_EVIDENCE,
            f"evidence {item.evidence_id!r} is outside the decision scope",
        )
    if packet.policy.permits_model_choice and "model" not in item.allowed_uses:
        return Refusal(
            RefusalCode.INVALID_EVIDENCE,
            f"evidence {item.evidence_id!r} is not permitted for model use",
        )
    if item.subject_revision != subject.revision:
        return Refusal(RefusalCode.STALE_INPUT, f"evidence {item.evidence_id!r} is stale")
    if item.source_tier not in _TIER_RANK:
        return Refusal(
            RefusalCode.INVALID_EVIDENCE,
            f"evidence {item.evidence_id!r} has an unknown source tier",
        )
    if (
        item.privacy_classification is PrivacyClass.PROHIBITED
        or "decision" not in item.allowed_uses
    ):
        return Refusal(
            RefusalCode.INVALID_EVIDENCE,
            f"evidence {item.evidence_id!r} is not permitted for decision use",
        )
    if item.expires_at is not None and now >= item.expires_at:
        return Refusal(RefusalCode.STALE_INPUT, f"evidence {item.evidence_id!r} has expired")
    if item.source_tier == "research" and (
        not item.research_receipt_digest or not verifier.verify_research_receipt(item)
    ):
        return Refusal(
            RefusalCode.INVALID_EVIDENCE,
            f"research evidence {item.evidence_id!r} lacks a current verified receipt",
        )
    return None


def candidate_eligibility(candidate: Candidate, packet: DecisionPacket) -> tuple[bool, str]:
    if candidate.action not in packet.allowed_actions:
        return False, f"action {candidate.action!r} is outside the packet vocabulary"
    index = {item.evidence_id: item for item in packet.evidence}
    cited = []
    for evidence_id in candidate.proof.cited_evidence_ids:
        item = index.get(evidence_id)
        if item is None:
            return False, f"cited evidence {evidence_id!r} is absent"
        cited.append(item)
    highest_tier = min(cited, key=lambda item: _TIER_RANK[item.source_tier]).source_tier
    if candidate.proof.source_tier != highest_tier:
        return False, "proof claims an authority tier its citations do not support"
    if candidate.effect is not None:
        if packet.policy.intensity is DecisionIntensity.ADVISORY:
            return False, "an advisory decision cannot carry an effect"
        unauthorized = set(candidate.effect.boundary_tags) - set(
            packet.policy.allowed_boundary_tags
        )
        if unauthorized:
            return False, f"effect contains unauthorized boundary tags: {sorted(unauthorized)}"
    return True, ""


def eligible_candidates(
    candidates: Iterable[Candidate], packet: DecisionPacket
) -> tuple[tuple[Candidate, ...], dict[str, str]]:
    eligible: list[Candidate] = []
    rejected: dict[str, str] = {}
    for candidate in candidates:
        ok, reason = candidate_eligibility(candidate, packet)
        if ok:
            eligible.append(candidate)
        else:
            rejected[candidate.candidate_id] = reason
    return tuple(eligible), rejected


def validated_entailed(candidate: Candidate, packet: DecisionPacket) -> bool:
    ok, _ = candidate_eligibility(candidate, packet)
    return (
        ok and candidate.proof.claimed_entailed and candidate.proof.source_tier in ENTAILING_TIERS
    )
