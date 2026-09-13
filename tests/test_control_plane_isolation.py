"""Two products on one core, and the seams where one could reach the other.

Every case here runs both products through the same registry, loader, gate and scheduler,
then asks whether anything belonging to one showed up in the other's answer. The leaks worth
testing are not symmetrical: data leaks through a scope, authority through a manifest, cost
through a budget, and failure through a fault that was not scoped to its product.
"""

from __future__ import annotations

import datetime as dt

import pytest

from aeos_kernel import (
    Comparison,
    ContractError,
    ExitSet,
    FcraPosture,
    GapRow,
    GapSeverity,
    Gate,
    GateOutcome,
    Gating,
    LiabilityClass,
    ModuleRegistry,
    MoveRequest,
    PriorityClass,
    ProductFault,
    ProductManifest,
    RequestedBy,
    Run,
    RunStatus,
    Signal,
    SignalPredicate,
    Stage,
    admit_move,
    evaluate_gate,
    latest_signal,
    load_modules,
    register_product,
)
from tests.factories_control_plane import (
    APP_FAMILY,
    DESK_FAMILY,
    NOW,
    PIPELINE_RAILS,
    TODAY,
    app_instance,
    desk_instance,
    family_registry,
    manifest,
    outreach_module,
    pipeline_module,
)

DESK = "fictional-desk"
APP = "fictional-app"


def both_registered() -> None:
    """Both products admitted by one registry, which is the premise of every case here."""

    registry = family_registry()
    for instance, modules in (
        (desk_instance(), ("pipeline", "commercial")),
        (app_instance(), ("pipeline",)),
    ):
        refusal = register_product(
            registry=registry,
            instance=instance,
            manifest=manifest(instance.slug, modules=modules),
            detected_at=NOW,
        )
        assert refusal is None, refusal


def test_the_two_products_share_one_registry_and_one_core() -> None:
    both_registered()
    assert {DESK_FAMILY.key, APP_FAMILY.key} <= set(family_registry().keys)


def test_one_product_s_gaps_never_enter_the_other_s_gate() -> None:
    """Data leak. A gate reads gaps in its own scope; another product's are not its business."""

    gate = Gate(
        gate_id="scale",
        module_key="outreach",
        from_stage=Stage.VALIDATE,
        to_stage=Stage.SCALE,
        exit_set=ExitSet(name="scale", max_open_error_gaps=0, gap_types_in_scope=("anything",)),
    )
    desk_gap = GapRow(
        gap_type="anything",
        severity=GapSeverity.ERROR,
        product_slug=DESK,
        subject_ref="desk-thing",
        reason="the desk has a problem",
        detected_at=NOW,
    )
    app_run = Run(
        run_id="run-app",
        product_slug=APP,
        module_key="outreach",
        stage=Stage.VALIDATE,
        status=RunStatus.RUNNING,
        started_at=NOW,
    )
    passed = evaluate_gate(gate=gate, run=app_run, signals=(), gaps=(desk_gap,), evaluated_at=NOW)
    assert passed.outcome is GateOutcome.PASS
    # The control: the same gap in the app's own scope does block it, so the pass above is
    # the scope working rather than the gate ignoring gaps.
    own_gap = GapRow(
        gap_type="anything",
        severity=GapSeverity.ERROR,
        product_slug=APP,
        subject_ref="app-thing",
        reason="the app has a problem",
        detected_at=NOW,
    )
    blocked = evaluate_gate(gate=gate, run=app_run, signals=(), gaps=(own_gap,), evaluated_at=NOW)
    assert blocked.outcome is GateOutcome.BLOCK


def test_one_product_s_measurements_never_answer_for_the_other() -> None:
    """Data leak through a metric. A healthy desk must not make the app look healthy."""

    desk_healthy = Signal(
        product_slug=DESK, metric="reply_rate", value=0.9, window="7d", ts=NOW
    )
    assert latest_signal(
        (desk_healthy,), product_slug=APP, metric="reply_rate", window="7d"
    ) is None
    predicate = SignalPredicate("reply_rate", "7d", Comparison.AT_LEAST, 0.03)
    # For the app the metric is unmeasured, which is not the desk's 0.9 and not zero either.
    assert "has not been measured" in predicate.unmet_reason((desk_healthy,), product_slug=APP)
    assert predicate.unmet_reason((desk_healthy,), product_slug=DESK) == ""


def test_one_product_s_credential_scope_grants_the_other_nothing() -> None:
    """Authority leak. A channel the desk may post on is not a channel the app may post on."""

    desk_manifest = manifest(DESK, credential_scopes={"shared-channel": ["post_update"]})
    app_manifest = manifest(APP, credential_scopes={})
    assert desk_manifest.permits(channel="shared-channel", move_type="post_update")
    assert not app_manifest.permits(channel="shared-channel", move_type="post_update")


def test_one_product_s_gating_and_liability_do_not_travel_to_the_other() -> None:
    """Authority leak through policy. Each product's manifest answers only for itself."""

    strict = ProductManifest(
        product_slug=DESK,
        version="1.0.0",
        modules_enabled=("pipeline",),
        tone_profile={},
        fcra_posture=FcraPosture.ACCEPTS_CRA,
        credential_scopes={},
        budget_caps={"llm_cost_usd_day": 1.0},
        gating=Gating(judgment_confidence_gate=0.99, park_ttl_hours=1),
        liability_class=LiabilityClass.C,
        approval_policy_ref="desk.counsel_attested",
    )
    relaxed = manifest(APP)
    assert strict.liability_class is LiabilityClass.C
    assert relaxed.liability_class is LiabilityClass.A
    assert strict.gating.judgment_confidence_gate != relaxed.gating.judgment_confidence_gate
    assert strict.approval_policy_ref != relaxed.approval_policy_ref
    assert strict.fcra_posture is not relaxed.fcra_posture


def test_one_product_s_budget_is_not_the_other_s() -> None:
    """Cost leak. A cap is a property of the product that declared it."""

    capped = manifest(DESK)
    uncapped = ProductManifest(
        product_slug=APP,
        version="1.0.0",
        modules_enabled=("pipeline",),
        tone_profile={},
        fcra_posture=FcraPosture.OUTSIDE_FCRA,
        credential_scopes={},
        budget_caps={},
        gating=Gating(),
        liability_class=LiabilityClass.A,
        approval_policy_ref="fictional.owner_attested",
    )
    assert capped.budget_cap("llm_cost_usd_day") == 3.0
    assert uncapped.budget_cap("llm_cost_usd_day") is None


def test_one_product_s_fault_does_not_halt_the_other() -> None:
    """Failure leak. This is the one the shared-channel carve-out deliberately excepts."""

    family = outreach_module().family("post_update")
    assert family is not None
    fault = ProductFault(
        product_slug=DESK,
        fault_type="module_degraded",
        reason="the desk's provider is failing",
        detected_at=NOW,
    )

    def request(slug: str) -> MoveRequest:
        return MoveRequest(
            request_id=f"request-{slug}",
            product_slug=slug,
            move_type="post_update",
            as_of=TODAY,
            priority_class=PriorityClass.NORMAL,
            requested_by=RequestedBy.SCHEDULE,
            requested_at=NOW,
        )

    assert admit_move(
        request=request(APP), family=family, faults=(fault,), channels=(), now=NOW
    ) is None
    refused = admit_move(
        request=request(DESK), family=family, faults=(fault,), channels=(), now=NOW
    )
    assert refused is not None
    assert refused.scope == f"product:{DESK}"


def test_one_product_s_refused_module_does_not_refuse_the_other_s() -> None:
    """Failure leak through loading. Each product's module set is decided on its own manifest."""

    registry = ModuleRegistry((pipeline_module(), outreach_module()))
    broken = load_modules(
        registry=registry,
        manifest=manifest(DESK, modules=("pipeline", "outreach"), credential_scopes={}),
        available_rails=PIPELINE_RAILS,
        detected_at=NOW,
    )
    healthy = load_modules(
        registry=registry,
        manifest=manifest(APP, modules=("pipeline", "outreach")),
        available_rails=PIPELINE_RAILS,
        detected_at=NOW,
    )
    assert broken.refused == ("outreach",)
    assert healthy.refused == ()
    # And the gaps that explain the refusal belong to the product that had the problem.
    assert {gap.product_slug for gap in broken.gaps} == {DESK}
    assert healthy.gaps == ()


def test_a_product_cannot_be_registered_under_another_product_s_profile() -> None:
    """Identity leak. A profile carries the slug it was built for, and answers for no other."""

    with pytest.raises(ContractError, match="belongs to a different product"):
        from dataclasses import replace

        replace(app_instance(), slug=DESK)


def test_a_manifest_cannot_be_used_for_a_product_it_does_not_name() -> None:
    refusal = register_product(
        registry=family_registry(),
        instance=app_instance(),
        manifest=manifest(DESK),
        detected_at=NOW,
    )
    assert refusal is not None
    assert "belongs to a different product" in refusal.reason


def test_the_shared_channel_carve_out_is_the_one_deliberate_exception() -> None:
    """Failure does cross for a shared sending domain, and only for its outbound.

    Naming it here keeps it an exception somebody chose rather than a leak nobody noticed.
    """

    from aeos_kernel import Channel, ChannelKind, ChannelState

    channel = Channel(
        key="shared-domain",
        kind=ChannelKind.EMAIL_DOMAIN,
        state=ChannelState.COOLDOWN,
        product_slugs=(DESK, APP),
        cooldown_until=NOW + dt.timedelta(hours=6),
        cooldown_reason="complaints on this sending domain",
    )
    family = outreach_module().family("post_update")
    assert family is not None

    def request(slug: str) -> MoveRequest:
        return MoveRequest(
            request_id=f"request-{slug}",
            product_slug=slug,
            move_type="post_update",
            as_of=TODAY,
            priority_class=PriorityClass.NORMAL,
            requested_by=RequestedBy.SCHEDULE,
            requested_at=NOW,
        )

    for slug in (DESK, APP):
        refusal = admit_move(
            request=request(slug),
            family=family,
            faults=(),
            channels=(channel,),
            channel_key="shared-domain",
            now=NOW,
        )
        assert refusal is not None
        assert refusal.scope == "channel:shared-domain"
    # Everything not sending on that domain keeps draining for both products.
    coverage = pipeline_module().family("capture_coverage")
    assert coverage is not None
    for slug in (DESK, APP):
        assert admit_move(
            request=request(slug), family=coverage, faults=(), channels=(channel,), now=NOW
        ) is None
