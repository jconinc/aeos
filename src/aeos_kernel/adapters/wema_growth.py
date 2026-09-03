"""Wema daily-growth advisory interchange mappings.

The adapter receives only Wema's closed route catalogue, aggregate outcomes, source-status
receipts, and one reconstructed local-graph context. It knows nothing about Wema's database,
Desk session, provider credentials, or effect handlers. The resulting recommendation is advice
to prepare one route; it cannot contact a person, publish, spend, or approve the later package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
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

GROWTH_ADAPTER_ID = "wema.daily_growth"
GROWTH_ADAPTER_VERSION = "1"
GROWTH_ACTION = "prepare_reach_route"
GROWTH_SOURCE_REF_TYPE = "reach_route"
GROWTH_DECISION_KIND = "research_reach_route"


@dataclass(frozen=True, slots=True)
class WemaGrowthSourceStatus:
    source_id: str
    status: str
    evidence_count: int
    receipt_digest: str
    observed_at: str | None = None
    safe_error_code: str | None = None
    highlight: str | None = None

    def safe_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "evidence_count": self.evidence_count,
            "receipt_digest": self.receipt_digest,
            "observed_at": self.observed_at,
            "safe_error_code": self.safe_error_code,
            "highlight": self.highlight,
        }


@dataclass(frozen=True, slots=True)
class WemaReachRouteProjection:
    route_id: str
    label: str
    availability: str
    participation: str
    priority_rank: int
    priority_score: int
    signal: str
    reason: str
    attempts: int
    positive_replies: int
    qualified_relationships: int
    active_placements: int
    useful_outputs: int
    purchases: int
    contribution_minor: int
    founder_minutes: int
    cash_cost_minor: int
    discovery_source: str
    has_active_opportunity: bool = False

    def safe_payload(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "label": self.label,
            "availability": self.availability,
            "participation": self.participation,
            "priority_rank": self.priority_rank,
            "priority_score": self.priority_score,
            "signal": self.signal,
            "reason": self.reason,
            "outcome": {
                "attempts": self.attempts,
                "positive_replies": self.positive_replies,
                "qualified_relationships": self.qualified_relationships,
                "active_placements": self.active_placements,
                "useful_outputs": self.useful_outputs,
                "purchases": self.purchases,
                "contribution_minor": self.contribution_minor,
                "founder_minutes": self.founder_minutes,
                "cash_cost_minor": self.cash_cost_minor,
            },
            "discovery_source": self.discovery_source,
            "has_active_opportunity": self.has_active_opportunity,
        }


@dataclass(frozen=True, slots=True)
class WemaGrowthProjection:
    analysis_day: date
    route_catalog_version: str
    ranking_policy_version: str
    routes: tuple[WemaReachRouteProjection, ...]
    source_statuses: tuple[WemaGrowthSourceStatus, ...]
    graph_snapshot_digest: str
    graph_generation: int

    @property
    def eligible_routes(self) -> tuple[WemaReachRouteProjection, ...]:
        return tuple(
            route
            for route in sorted(self.routes, key=lambda item: (item.priority_rank, item.route_id))
            if route.availability == "test_now" and not route.has_active_opportunity
        )

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.safe_payload())

    def safe_payload(self) -> dict[str, Any]:
        return {
            "analysis_day": self.analysis_day.isoformat(),
            "route_catalog_version": self.route_catalog_version,
            "ranking_policy_version": self.ranking_policy_version,
            "routes": [route.safe_payload() for route in self.routes],
            "source_statuses": [source.safe_payload() for source in self.source_statuses],
            "graph_snapshot_digest": self.graph_snapshot_digest,
            "graph_generation": self.graph_generation,
        }


def build_wema_growth_packet(
    *,
    tenant_id: str,
    projection: WemaGrowthProjection,
    authority_bundle_digest: str,
    source_head_pins: Mapping[str, str],
    policy: AuthorityPolicy,
    observed_at: datetime,
) -> DecisionPacket:
    """Build one source-pinned daily packet from the complete safe route projection."""

    source_ref = SourceRef(
        source_type="wema_growth_projection",
        source_id=projection.analysis_day.isoformat(),
        revision=projection.digest,
        digest=projection.digest,
    )
    subject = DecisionSubject(
        vertical_id="wema",
        tenant_id=tenant_id,
        subject_id=f"growth:{projection.analysis_day.isoformat()}",
        subject_kind="daily_growth",
        revision=projection.digest,
        content_digest=projection.digest,
        attributes={
            "analysis_day": projection.analysis_day.isoformat(),
            "route_catalog_version": projection.route_catalog_version,
            "ranking_policy_version": projection.ranking_policy_version,
        },
        source_refs=(source_ref,),
        allowed_uses=("decision",),
    )
    evidence_payloads = (
        (
            "growth_selection_policy",
            "product_policy",
            {
                "selection": "lowest priority_rank among test_now routes without active work",
                "maximum_recommendations": 1,
                "route_catalog_version": projection.route_catalog_version,
                "ranking_policy_version": projection.ranking_policy_version,
                "effect": "none",
            },
            SourceRef(
                source_type="wema_reach_policy",
                source_id=projection.route_catalog_version,
                revision=projection.ranking_policy_version,
                digest=stable_fingerprint(
                    {
                        "catalog": projection.route_catalog_version,
                        "ranking": projection.ranking_policy_version,
                    }
                ),
            ),
        ),
        (
            "reach_route_portfolio",
            "host_state",
            {"routes": [route.safe_payload() for route in projection.routes]},
            source_ref,
        ),
        (
            "growth_source_statuses",
            "observation",
            {"sources": [source.safe_payload() for source in projection.source_statuses]},
            SourceRef(
                source_type="wema_growth_sources",
                source_id=projection.analysis_day.isoformat(),
                revision=projection.digest,
                digest=stable_fingerprint(
                    [source.safe_payload() for source in projection.source_statuses]
                ),
            ),
        ),
        (
            "growth_graph_snapshot",
            "graph",
            {
                "snapshot_digest": projection.graph_snapshot_digest,
                "generation": projection.graph_generation,
            },
            SourceRef(
                source_type="aeos_graph_snapshot",
                source_id="wema:daily_growth",
                revision=str(projection.graph_generation),
                digest=projection.graph_snapshot_digest,
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
            allowed_uses=("decision",),
        )
        for evidence_id, source_tier, payload, ref in evidence_payloads
    )
    return build_decision_packet(
        packet_id="wema_growth_packet_" + projection.digest[:24],
        subject=subject,
        evidence=evidence,
        authority_bundle_digest=authority_bundle_digest,
        policy=policy,
        allowed_actions=(GROWTH_ACTION,),
        source_head_pins=dict(source_head_pins),
        adapter_id=GROWTH_ADAPTER_ID,
        adapter_version=GROWTH_ADAPTER_VERSION,
        created_at=observed_at,
    )


def growth_route_candidates(projection: WemaGrowthProjection) -> tuple[Candidate, ...]:
    """Map every currently eligible route; only the ranked first route is entailed."""

    eligible = projection.eligible_routes
    if not eligible:
        return ()
    selected_id = eligible[0].route_id
    current_highlights = tuple(
        source.highlight
        for source in projection.source_statuses
        if source.status == "current" and source.highlight is not None
    )
    evidence_sentence = (
        f" Current evidence: {current_highlights[0]}"
        if current_highlights
        else (
            " No current external research highlight is available, so this uses verified "
            "Wema results."
        )
    )
    return tuple(
        Candidate(
            candidate_id=f"prepare:{route.route_id}",
            action=GROWTH_ACTION,
            title=f"Prepare one {route.label} test",
            explanation=(
                f"{route.reason} Start with one public, rules-checked target; nothing is sent "
                f"or published by this step.{evidence_sentence}"
            ),
            expected_benefit=(
                "One measurable route moves forward without asking the founder to sort the "
                "whole channel catalogue."
            ),
            uncertainty=(
                "Source evidence is incomplete."
                if any(source.status != "current" for source in projection.source_statuses)
                else "Results remain uncertain until this route is tested and verified."
            ),
            proof=EntailmentProof(
                source_tier="product_policy",
                cited_evidence_ids=(
                    "growth_selection_policy",
                    "reach_route_portfolio",
                    "growth_source_statuses",
                    "growth_graph_snapshot",
                ),
                reason=(
                    "The governed route ranking and availability prerequisites select this "
                    "single unblocked route."
                ),
                claimed_entailed=route.route_id == selected_id,
            ),
            effect=None,
        )
        for route in eligible
    )


def to_growth_owned_action_values(
    recommendation: Recommendation,
    *,
    packet: DecisionPacket,
    selected: WemaReachRouteProjection,
    alternatives: Sequence[WemaReachRouteProjection],
    source_statuses: Sequence[WemaGrowthSourceStatus] = (),
) -> dict[str, Any]:
    """Project one advice-only decision into Wema's existing operator work queue."""

    return {
        "module": "relationships",
        "title": f"Prepare one {selected.label} test"[:200],
        "body": recommendation.explanation,
        "evidence": {
            "aeos_decision_id": recommendation.decision_id,
            "aeos_decision_revision": recommendation.decision_revision,
            "recommendation_digest": recommendation.digest,
            "packet_digest": packet.packet_digest,
            "growth_projection_digest": packet.subject.content_digest,
            "analysis_day": packet.subject.attributes["analysis_day"],
            "route_id": selected.route_id,
            "priority_rank": selected.priority_rank,
            "priority_score": selected.priority_score,
            "signal": selected.signal,
            "alternative_route_ids": [route.route_id for route in alternatives[:5]],
            "source_highlights": [
                source.highlight
                for source in source_statuses
                if source.status == "current" and source.highlight is not None
            ][:4],
        },
        "effort": "30min",
        "impact_label": "ordinary",
        "rank_class": "compounding",
        "requires_founder_judgment": False,
        "source_ref_type": GROWTH_SOURCE_REF_TYPE,
        "source_ref_id": selected.route_id,
        "decision_kind": GROWTH_DECISION_KIND,
    }
