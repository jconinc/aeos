from __future__ import annotations

from datetime import date

import pytest

from aeos_kernel import (
    AuthorityLevel,
    AuthorityPolicy,
    DecisionEngine,
    DecisionIntensity,
    DecisionStatus,
)
from aeos_kernel.adapters.multiagent import (
    WlgCandidate,
    WlgEvidence,
    build_wlg_packet,
    map_wlg_candidate,
    to_wlg_decision_record,
)
from aeos_kernel.adapters.wema import (
    ARTICLE_DECISION_KIND,
    ARTICLE_REVISION_OPERATION,
    ARTICLE_SOURCE_REF_TYPE,
    WemaArticleProjection,
    build_wema_article_packet,
    prepared_revision_candidate,
    to_owned_action_values,
)
from aeos_kernel.adapters.wema_growth import (
    GROWTH_DECISION_KIND,
    WemaGrowthProjection,
    WemaGrowthSourceStatus,
    WemaReachRouteProjection,
    build_wema_growth_packet,
    growth_route_candidates,
    to_growth_owned_action_values,
)
from aeos_kernel.adapters.wema_reviews import (
    REVIEW_DECISION_KIND,
    WemaReviewProjection,
    WemaReviewResponse,
    build_wema_review_packet,
    review_follow_up_candidate,
    to_review_owned_action_values,
)
from tests.factories import NOW, AcceptingVerifier, FixedClock, policy


def article() -> WemaArticleProjection:
    return WemaArticleProjection(
        article_id="article-1",
        version_id="version-1",
        version=1,
        digest="a" * 64,
        status="draft",
        artifact_status="draft",
        title="A steady first hour",
        question="What should I do first when care suddenly changes?",
        answer_first="Start by writing down what changed and who needs to know.",
        meta_description="A calm first-hour checklist for a sudden change in family care.",
        article_class="care",
        quality_ready=False,
        needs_attention=("source_refs",),
        word_count=740,
        reading_grade=7.1,
        required_reviews=("founder",),
        approved_reviews=(),
    )


def test_wema_adapter_builds_privacy_minimized_digest_bound_article_packet() -> None:
    result = build_wema_article_packet(
        tenant_id="wema",
        article=article(),
        analysis={"answer_clarity": "good", "missing": ["source_refs"]},
        aggregate_outcomes={"status": "insufficient_evidence"},
        canon_guidance={"voice": "warm_specific_plain"},
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_git": "76e7c0f4fb1df28a9b77a02e1743eec83cd5a249"},
        allowed_actions=("add_sources",),
        policy=policy(),
        observed_at=NOW,
    )
    assert result.has_canonical_digest()
    assert result.subject.subject_kind == "article_revision"
    assert {item.evidence_id for item in result.evidence} == {
        "article_projection",
        "article_analysis",
        "article_outcomes",
        "wema_canon_guidance",
    }
    serialized = str(result.as_dict()).lower()
    for prohibited in ("email", "patient", "caregiver_name", "credential", "visitor_history"):
        assert prohibited not in serialized


def test_wema_recommendation_projects_to_real_owned_action_columns() -> None:
    decision_packet = build_wema_article_packet(
        tenant_id="wema",
        article=article(),
        analysis={"missing": ["source_refs"]},
        aggregate_outcomes={"status": "insufficient_evidence"},
        canon_guidance={"source_rule": "cite claims that need support"},
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_git": "76e7c0f4fb1df28a9b77a02e1743eec83cd5a249"},
        allowed_actions=("add_sources",),
        policy=policy(),
        observed_at=NOW,
    )
    candidate = prepared_revision_candidate(
        candidate_id="add-sources",
        action="add_sources",
        title="Check the sources for one article",
        explanation="The article is useful, but its care claims still need their source links.",
        expected_benefit="Readers can see where the practical guidance comes from.",
        evidence_ids=("article_projection",),
        source_tier="host_state",
        article_id="article-1",
        expected_digest="a" * 64,
        prepared_draft={"title": "A steady first hour", "source_refs": ["source-1"]},
        claimed_entailed=True,
    )
    recommendation = DecisionEngine(verifier=AcceptingVerifier(), clock=FixedClock()).decide(
        decision_packet, (candidate,)
    )
    values = to_owned_action_values(recommendation, packet=decision_packet, candidate=candidate)
    assert recommendation.status is DecisionStatus.PROPOSED
    assert candidate.effect is not None and candidate.effect.operation == ARTICLE_REVISION_OPERATION
    assert values["source_ref_type"] == ARTICLE_SOURCE_REF_TYPE
    assert values["source_ref_id"] == "article-1"
    assert values["decision_kind"] == ARTICLE_DECISION_KIND
    assert values["requires_founder_judgment"] is True
    assert set(values["evidence"]) == {
        "aeos_decision_id",
        "aeos_decision_revision",
        "recommendation_digest",
        "packet_digest",
        "article_digest",
    }


def review() -> WemaReviewProjection:
    return WemaReviewProjection(
        submission_id="review-1",
        packet_kind="site",
        release="release-r32",
        inventory_digest="b" * 64,
        payload_digest="d" * 64,
        responses=(
            WemaReviewResponse(
                item_id="home.opening",
                decision="needs_change",
                note="The opening feels crowded on my phone.",
            ),
            WemaReviewResponse(item_id="privacy", decision="looks_good"),
        ),
    )


def test_wema_review_adapter_is_internal_model_forbidden_and_identity_minimized() -> None:
    current = review()
    decision_packet = build_wema_review_packet(
        tenant_id="wema",
        review=current,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_release": "release-r32"},
        policy=policy(human=False, intensity=DecisionIntensity.ADVISORY),
        observed_at=NOW,
    )
    assert decision_packet.has_canonical_digest()
    assert decision_packet.subject.subject_kind == "deployment_review"
    assert decision_packet.subject.allowed_uses == ("decision",)
    assert decision_packet.evidence[0].allowed_uses == ("decision",)
    serialized = str(decision_packet.as_dict()).lower()
    assert "opening feels crowded" in serialized
    assert "reviewer" not in serialized
    assert "email" not in serialized


def test_wema_review_attention_becomes_one_aeos_operator_follow_up() -> None:
    current = review()
    decision_packet = build_wema_review_packet(
        tenant_id="wema",
        review=current,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_release": "release-r32"},
        policy=policy(human=False, intensity=DecisionIntensity.ADVISORY),
        observed_at=NOW,
    )
    candidate = review_follow_up_candidate(current)
    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision=current.payload_digest), clock=FixedClock()
    ).decide(decision_packet, (candidate,))
    values = to_review_owned_action_values(
        recommendation, packet=decision_packet, candidate=candidate
    )
    assert recommendation.status is DecisionStatus.PROPOSED
    assert recommendation.selection_mode == "auto_entailed"
    assert candidate.effect is None
    assert values["decision_kind"] == REVIEW_DECISION_KIND
    assert values["requires_founder_judgment"] is False
    assert values["evidence"]["attention_count"] == 1
    assert "opening feels crowded" not in str(values).lower()


def test_wema_review_all_clear_does_not_invent_work() -> None:
    current = WemaReviewProjection(
        submission_id="review-clear",
        packet_kind="articles",
        release="release-r32",
        inventory_digest="b" * 64,
        payload_digest="e" * 64,
        responses=(WemaReviewResponse(item_id="article.one", decision="looks_good"),),
    )
    with pytest.raises(ValueError, match="does not entail"):
        review_follow_up_candidate(current)


def _growth_route(route_id: str, rank: int, *, active: bool = False) -> WemaReachRouteProjection:
    return WemaReachRouteProjection(
        route_id=route_id,
        label=route_id.replace("_", " ").title(),
        availability="test_now",
        participation="text_only",
        priority_rank=rank,
        priority_score=100 - rank,
        signal="untried",
        reason="This route has high repeat leverage and no prior test.",
        attempts=0,
        positive_replies=0,
        qualified_relationships=0,
        active_placements=0,
        useful_outputs=0,
        purchases=0,
        contribution_minor=0,
        founder_minutes=0,
        cash_cost_minor=0,
        discovery_source="public directory",
        has_active_opportunity=active,
    )


def test_wema_growth_adapter_selects_one_ranked_route_and_retains_alternatives() -> None:
    projection = WemaGrowthProjection(
        analysis_day=date(2026, 9, 3),
        route_catalog_version="wema-reach-routes@1",
        ranking_policy_version="reach-ranking@1",
        routes=(
            _growth_route("already_active", 1, active=True),
            _growth_route("cms_guide_participants", 2),
            _growth_route("care_act_discharge", 3),
        ),
        source_statuses=(
            WemaGrowthSourceStatus(
                "gsc",
                "current",
                1,
                "a" * 64,
                highlight="Google showed /care 12 times and sent 2 visits.",
            ),
            WemaGrowthSourceStatus("x", "unavailable", 0, "b" * 64),
        ),
        graph_snapshot_digest="d" * 64,
        graph_generation=4,
    )
    packet = build_wema_growth_packet(
        tenant_id="wema",
        projection=projection,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_release": "76e7c0f4fb1df28a9b77a02e1743eec83cd5a249"},
        policy=policy(human=False, intensity=DecisionIntensity.ADVISORY),
        observed_at=NOW,
    )
    candidates = growth_route_candidates(projection)
    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision=projection.digest), clock=FixedClock()
    ).decide(packet, candidates)
    selected = projection.eligible_routes[0]
    values = to_growth_owned_action_values(
        recommendation,
        packet=packet,
        selected=selected,
        alternatives=projection.eligible_routes[1:],
        source_statuses=projection.source_statuses,
    )

    assert packet.has_canonical_digest()
    assert recommendation.status is DecisionStatus.PROPOSED
    assert recommendation.selection_mode == "auto_entailed"
    assert recommendation.selected_candidate_id == "prepare:cms_guide_participants"
    assert recommendation.rejected_alternatives == ("prepare:care_act_discharge",)
    assert values["decision_kind"] == GROWTH_DECISION_KIND
    assert values["requires_founder_judgment"] is False
    assert values["evidence"]["alternative_route_ids"] == ["care_act_discharge"]
    assert values["evidence"]["source_highlights"] == [
        "Google showed /care 12 times and sent 2 visits."
    ]
    assert "Current evidence: Google showed /care" in recommendation.explanation
    serialized = str(packet.as_dict()).lower()
    for prohibited in ("email", "password", "patient", "caregiver_name", "raw_reply"):
        assert prohibited not in serialized


def test_multiagent_adapter_preserves_project_revision_evidence_and_repair_plan() -> None:
    wlg_policy = AuthorityPolicy(
        policy_id="wlg-repair",
        policy_version="1",
        level=AuthorityLevel.DETERMINISTIC,
        intensity=DecisionIntensity.INTERNAL_EFFECT,
        allowed_boundary_tags=("wlg_graph_mutation",),
    )
    decision_packet = build_wlg_packet(
        project_id="project-one",
        unit_id="unit-one",
        graph_revision=42,
        finding="one registered edge is absent",
        unit_digest="a" * 64,
        evidence=(
            WlgEvidence(
                evidence_id="graph-edge-evidence",
                source_tier="graph",
                project_id="project-one",
                graph_revision=42,
                payload={"from": "one", "to": "two"},
                source_ref="shape-one",
            ),
        ),
        canon_bundle_digest="c" * 64,
        source_head_pins={"coordination_head": "d99002a1903a56b5601d7ec3455e5dfa43028935"},
        allowed_actions=("link",),
        policy=wlg_policy,
        created_at=NOW,
    )
    candidate = map_wlg_candidate(
        WlgCandidate(
            candidate_id="link-one-two",
            action="link",
            title="Link the two registered shapes",
            rationale="The current graph evidence uniquely identifies both endpoints.",
            source_tier="graph",
            cited_evidence_ids=("graph-edge-evidence",),
            claimed_entailed=True,
            repair_plan={"ops": [{"op_type": "link", "subject_id": "one", "target_id": "two"}]},
            static_gate_passed=True,
            repair_contract_digest="d" * 64,
        )
    )
    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision="42"), clock=FixedClock()
    ).decide(decision_packet, (candidate,))
    record = to_wlg_decision_record(recommendation, packet=decision_packet, candidate=candidate)
    assert recommendation.selection_mode == "auto_entailed"
    assert record["project_id"] == "project-one"
    assert record["unit_id"] == "unit-one"
    assert record["decision"] == "link"
    assert record["needs_operator"] == "no"
    assert record["typed_op_plan"]["repair_plan"]["ops"][0]["target_id"] == "two"
    assert record["typed_op_plan"]["static_gate_receipt"] == {
        "passed": True,
        "repair_contract_digest": "d" * 64,
    }
    assert record["audit"]["expected_receipt"]["kind"] == "effect_commit"
    with pytest.raises(ValueError, match="exact selected candidate"):
        to_wlg_decision_record(recommendation, packet=decision_packet, candidate=None)


def test_multiagent_adapter_contracts_are_strict_immutable_and_gate_bound() -> None:
    current_evidence = WlgEvidence(
        evidence_id="e1",
        source_tier="graph",
        project_id="project-one",
        graph_revision=1,
        payload={"nested": {"value": 1}},
        source_ref="shape-one",
    )
    with pytest.raises(TypeError, match="immutable"):
        current_evidence.payload["nested"]["value"] = 2
    with pytest.raises(ValueError, match="positive"):
        WlgEvidence(
            evidence_id="e1",
            source_tier="graph",
            project_id="project-one",
            graph_revision=0,
            payload={},
            source_ref="shape-one",
        )
    ungated = WlgCandidate(
        candidate_id="candidate",
        action="link",
        title="Link a registered shape",
        rationale="The evidence grounds the exact edge.",
        source_tier="graph",
        cited_evidence_ids=("e1",),
        claimed_entailed=True,
        repair_plan={"ops": []},
        static_gate_passed=False,
        repair_contract_digest="d" * 64,
    )
    with pytest.raises(ValueError, match="static gate"):
        map_wlg_candidate(ungated)


# ── wema.mail_triage@1 ────────────────────────────────────────────────────────

from aeos_kernel.adapters.wema_mail import (  # noqa: E402
    MAIL_DECISION_KIND,
    MAIL_SOURCE_REF_TYPE,
    REFUND_OPERATION,
    SEND_REPLY_OPERATION,
    WemaMailboxPolicy,
    WemaMailMessageProjection,
    WemaOrderContext,
    build_wema_mail_packet,
    mail_candidates,
    to_mail_owned_action_values,
)


def _mail_policy(*, outward: bool) -> AuthorityPolicy:
    return AuthorityPolicy(
        policy_id="wema.mail.reply" if outward else "wema.mail.read",
        policy_version="1",
        level=AuthorityLevel.STANDARD_DEFAULT,
        intensity=(
            DecisionIntensity.OUTWARD_OR_IRREVERSIBLE if outward else DecisionIntensity.ADVISORY
        ),
        allowed_boundary_tags=("outbound_mail", "payment") if outward else (),
        required_capacity="founder",
        requires_human_attestation=True,
        permits_model_choice=False,
    )


def _mailbox() -> WemaMailboxPolicy:
    return WemaMailboxPolicy(
        mailbox_id="support",
        purpose="support",
        owner="founder",
        response_promise_hours=48,
        allowed_actions=("refund_and_reply", "reply_only", "open_mailbox"),
        registry_version="mailboxes@1",
        registry_digest="d" * 64,
    )


def _mail_message(
    *,
    risk: bool = False,
    satisfied: tuple[str, ...] = ("order_matched", "order_refundable"),
) -> WemaMailMessageProjection:
    return WemaMailMessageProjection(
        message_id="019a-message",
        mailbox_id="support",
        classification="refund_request",
        risk_flag=risk,
        owner="john" if risk else "founder",
        recommended_action="refund_and_reply",
        fallback_action="reply_only",
        requires=("order_matched", "order_refundable"),
        requires_satisfied=satisfied,
        template_id="refund_done",
        safe_summary="Asks for a refund. Order from 12 days ago, $49.",
        received_at=NOW,
        deadline_at=NOW,
    )


def _order(*, refundable: bool = True) -> WemaOrderContext:
    return WemaOrderContext(
        order_id="019a-order",
        status="fulfilled",
        amount_minor=4900,
        currency="USD",
        days_since_purchase=12,
        refundable=refundable,
    )


def test_wema_mail_projections_refuse_addresses_and_unregistered_values() -> None:
    with pytest.raises(ValueError, match="look like mailboxes@1"):
        WemaMailboxPolicy(
            mailbox_id="support",
            purpose="support",
            owner="founder",
            response_promise_hours=48,
            allowed_actions=("reply_only",),
            registry_version="someone@example.test",
            registry_digest="d" * 64,
        )
    with pytest.raises(ValueError, match="address"):
        WemaMailboxPolicy(
            mailbox_id="support@example.test",
            purpose="support",
            owner="founder",
            response_promise_hours=48,
            allowed_actions=("reply_only",),
            registry_version="mailboxes@1",
            registry_digest="d" * 64,
        )
    with pytest.raises(ValueError, match="registered mail action"):
        WemaMailboxPolicy(
            mailbox_id="support",
            purpose="support",
            owner="founder",
            response_promise_hours=48,
            allowed_actions=("suppress_only",),
            registry_version="mailboxes@1",
            registry_digest="d" * 64,
        )
    with pytest.raises(ValueError, match="satisfied requirement"):
        _mail_message(satisfied=("card_present",))
    with pytest.raises(ValueError, match="support reply can act on"):
        WemaOrderContext(
            order_id="o",
            status="refunded",
            amount_minor=1,
            currency="USD",
            days_since_purchase=1,
            refundable=False,
        )


def test_wema_mail_refund_is_the_single_entailed_candidate_with_an_outward_effect() -> None:
    mailbox, message, order = _mailbox(), _mail_message(), _order()
    packet = build_wema_mail_packet(
        tenant_id="wema",
        mailbox=mailbox,
        message=message,
        order=order,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_mailbox_registry": "mailboxes@1"},
        policy=_mail_policy(outward=True),
        observed_at=NOW,
    )
    assert packet.has_canonical_digest()
    assert packet.subject.subject_kind == "mail_message"
    assert packet.subject.attributes["entailed_action"] == "refund_and_reply"
    assert [item.evidence_id for item in packet.evidence] == [
        "mailbox_policy",
        "mail_message_projection",
        "order_context",
    ]
    candidates = mail_candidates(mailbox, message, order)
    assert [c.action for c in candidates] == ["refund_and_reply", "reply_only", "open_mailbox"]
    assert [c.proof.claimed_entailed for c in candidates] == [True, False, False]
    refund = candidates[0]
    assert refund.effect is not None
    assert refund.effect.operation == REFUND_OPERATION
    assert refund.effect.boundary_tags == ("outbound_mail", "payment")
    assert refund.effect.cost_ceiling_minor_units == 4900
    assert candidates[1].effect is not None
    assert candidates[1].effect.operation == SEND_REPLY_OPERATION
    assert candidates[2].effect is None

    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision=packet.subject.revision), clock=FixedClock()
    ).decide(packet, candidates)
    assert recommendation.status is DecisionStatus.PROPOSED
    assert recommendation.selection_mode == "auto_entailed"
    assert recommendation.selected_candidate_id == "mail-refund-and-reply"
    assert recommendation.model_calls == ()

    values = to_mail_owned_action_values(
        recommendation,
        packet=packet,
        candidate=refund,
        mailbox=mailbox,
        message=message,
        order=order,
        rank_class="customer_recovery",
    )
    assert values["title"] == "Support: Asks for a refund."
    assert values["body"] == "Recommended: refund $49 and send the reply below."
    assert values["requires_founder_judgment"] is True
    assert values["source_ref_type"] == MAIL_SOURCE_REF_TYPE
    assert values["decision_kind"] == MAIL_DECISION_KIND
    assert values["evidence"]["aeos_decision_id"] == recommendation.decision_id
    assert values["evidence"]["recommended_action"] == "refund_and_reply"


def test_wema_mail_facts_that_do_not_hold_entail_the_fallback() -> None:
    mailbox = _mailbox()
    message = _mail_message(satisfied=("order_matched",))
    order = _order(refundable=False)
    candidates = mail_candidates(mailbox, message, order)
    # The refund is not offered without a refundable order; the fallback is entailed.
    assert [c.action for c in candidates] == ["reply_only", "open_mailbox"]
    assert candidates[0].proof.claimed_entailed is True
    packet = build_wema_mail_packet(
        tenant_id="wema",
        mailbox=mailbox,
        message=message,
        order=order,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_mailbox_registry": "mailboxes@1"},
        policy=_mail_policy(outward=True),
        observed_at=NOW,
    )
    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision=packet.subject.revision), clock=FixedClock()
    ).decide(packet, candidates)
    assert recommendation.selected_candidate_id == "mail-reply-only"


def test_wema_mail_a_risky_message_is_read_by_a_person_and_carries_no_effect() -> None:
    mailbox, message = _mailbox(), _mail_message(risk=True)
    assert message.entailed_action == "open_mailbox"
    candidates = mail_candidates(mailbox, message, None)
    assert candidates[0].action == "open_mailbox" and candidates[0].proof.claimed_entailed
    packet = build_wema_mail_packet(
        tenant_id="wema",
        mailbox=mailbox,
        message=message,
        order=None,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_mailbox_registry": "mailboxes@1"},
        policy=_mail_policy(outward=False),
        observed_at=NOW,
    )
    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision=packet.subject.revision), clock=FixedClock()
    ).decide(packet, candidates)
    assert recommendation.selected_candidate_id == "mail-open-mailbox"
    # The sending alternative is rejected under an advisory policy, not selected by accident.
    assert "mail-reply-only" in recommendation.rejected_alternatives
    values = to_mail_owned_action_values(
        recommendation,
        packet=packet,
        candidate=candidates[0],
        mailbox=mailbox,
        message=message,
        order=None,
        rank_class="critical_containment",
    )
    assert values["impact_label"] == "safety"
    assert values["requires_founder_judgment"] is False  # routed to John by the registry
    assert values["body"].startswith("Recommended: read it in the mailbox")


def test_wema_mail_inconsistent_host_facts_fail_loudly() -> None:
    mailbox, message = _mailbox(), _mail_message()
    with pytest.raises(ValueError, match="refundable matched order"):
        mail_candidates(mailbox, message, None)
    with pytest.raises(ValueError, match="disagree about the mailbox"):
        build_wema_mail_packet(
            tenant_id="wema",
            mailbox=WemaMailboxPolicy(
                mailbox_id="hello",
                purpose="general",
                owner="founder",
                response_promise_hours=72,
                allowed_actions=("reply_only", "open_mailbox"),
                registry_version="mailboxes@1",
                registry_digest="d" * 64,
            ),
            message=message,
            order=_order(),
            authority_bundle_digest="c" * 64,
            source_head_pins={"wema_mailbox_registry": "mailboxes@1"},
            policy=_mail_policy(outward=True),
            observed_at=NOW,
        )


def test_wema_mail_packet_and_card_carry_no_message_text() -> None:
    mailbox, message, order = _mailbox(), _mail_message(), _order()
    packet = build_wema_mail_packet(
        tenant_id="wema",
        mailbox=mailbox,
        message=message,
        order=order,
        authority_bundle_digest="c" * 64,
        source_head_pins={"wema_mailbox_registry": "mailboxes@1"},
        policy=_mail_policy(outward=True),
        observed_at=NOW,
    )
    candidates = mail_candidates(mailbox, message, order)
    recommendation = DecisionEngine(
        verifier=AcceptingVerifier(revision=packet.subject.revision), clock=FixedClock()
    ).decide(packet, candidates)
    values = to_mail_owned_action_values(
        recommendation,
        packet=packet,
        candidate=candidates[0],
        mailbox=mailbox,
        message=message,
        order=order,
        rank_class="customer_recovery",
    )
    serialized = (
        str(packet.as_dict()) + str([c.as_dict() for c in candidates]) + str(values)
    ).lower()
    # The registry version label is the one `@` allowed; every other `@` is an address.
    assert "@" not in serialized.replace("mailboxes@1", "")
    # Words a message would carry and a projection cannot: the adapter has no field for them.
    for forbidden in ("dear", "hi there", "regards", "from:"):
        assert forbidden not in serialized, forbidden
