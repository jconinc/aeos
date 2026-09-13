"""The remaining boundaries: registry identity, launch predicates, and pinned pointers.

A second pass at the same four kinds this lane's other boundary file covers — refusal,
identity, recovery, unknown-observation — against the conditions root's coverage measurement
still finds unreached on the joined source.

These are not line inventories. Each names a contract a caller depends on, and each fault has
the ordinary case beside it. Where a family of refusals shares one rule, the cases are
parameterized with genuinely different inputs rather than repeated.

No database, provider, sleep or network. Every fixture is a small immutable value.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.pipeline import (
    BindingStatus,
    ClaimState,
    CoverageSnapshot,
    GateManifestEntry,
    GateStatus,
    MirroredTask,
    PipelineGateDecision,
    PipelineGateKind,
    PipelineOutcome,
    PredicateKind,
    ProductGateManifest,
    Readiness,
    RegistryRef,
    ReleaseReadiness,
    TaskBatch,
    WLGProjectBinding,
    snapshot_identity,
)
from aeos_kernel.registry import (
    BusinessModel,
    BusinessModelType,
    FamilyProfile,
    FamilyRegistry,
    LifecycleStatus,
    ProductFamily,
    ProductFamilyKey,
    ProductInstance,
    ProfileFieldSpec,
    ProfileFieldType,
    ReleaseState,
    RevenueRecognition,
    SharedAssetBinding,
    SharedAssetKind,
    launch_blockers,
    register_product,
    validate_family_profile,
)
from aeos_kernel.scheduling import Channel, ChannelKind, ChannelState, SweepPlan
from tests.factories_control_plane import NOW, TODAY, manifest

SLUG = "fictional-app"
DIGEST = "0" * 64


# --------------------------------------------------------------------------------------
# pinned pointers — a replayable reference, or none
# --------------------------------------------------------------------------------------


def registry_ref(**kwargs: Any) -> RegistryRef:
    fields: dict[str, Any] = {
        "project_id": "fictional-project",
        "registry_locator": "fictional://requirements",
        "registry_sha256": DIGEST,
        "row_count": 12,
        "captured_at": NOW,
        "snapshot_ref": "snapshot:1",
        **kwargs,
    }
    return RegistryRef(**fields)


def test_a_registry_pointer_carries_the_digest_that_makes_it_replayable() -> None:
    assert registry_ref().registry_sha256 == DIGEST


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"project_id": ""}, "project_id"),
        ({"registry_locator": ""}, "registry_locator"),
        ({"snapshot_ref": ""}, "snapshot_ref"),
        ({"registry_sha256": "not-a-digest"}, "registry_sha256"),
        ({"row_count": -1}, "row count must be nonnegative"),
    ],
)
def test_a_pointer_that_could_not_be_replayed_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """A pointer without a digest is a description of a registry, not a reference to one."""

    with pytest.raises(ContractError, match=refusal):
        registry_ref(**kwargs)


def binding(**kwargs: Any) -> WLGProjectBinding:
    fields: dict[str, Any] = {
        "binding_id": "binding-1",
        "product_slug": SLUG,
        "project_id": "fictional-project",
        "requirements_ref": registry_ref(),
        "shape_ref": registry_ref(registry_locator="fictional://shapes"),
        "bound_at": NOW,
        "bound_by": "fictional.owner",
        **kwargs,
    }
    return WLGProjectBinding(**fields)


def test_a_binding_ties_one_product_to_one_build_project() -> None:
    assert binding().status is BindingStatus.ACTIVE


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        (
            {"requirements_ref": registry_ref(project_id="somebody-elses")},
            "requirements registry belongs to a different project",
        ),
        (
            {"shape_ref": registry_ref(project_id="somebody-elses")},
            "shape registry belongs to a different project",
        ),
        ({"status": "active"}, "binding status is not recognized"),
        ({"bound_by": ""}, "bound_by"),
    ],
)
def test_a_binding_that_points_somewhere_else_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """Identity: a binding whose registries belong to another project binds nothing."""

    with pytest.raises(ContractError, match=refusal):
        binding(**kwargs)


# --------------------------------------------------------------------------------------
# coverage — counts that describe a real reading
# --------------------------------------------------------------------------------------


def coverage(**kwargs: Any) -> CoverageSnapshot:
    fields: dict[str, Any] = {
        "snapshot_id": "coverage:1",
        "binding_id": "binding-1",
        "product_slug": SLUG,
        "snapshot_ref": "registry:1",
        "captured_at": NOW,
        "total_requirements": 10,
        "covered_requirements": 8,
        "uncovered_requirement_ids": ("REQ-1", "REQ-2"),
        **kwargs,
    }
    return CoverageSnapshot(**fields)


def test_an_ordinary_coverage_reading_is_accepted() -> None:
    assert coverage().coverage_pct == 0.8


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"total_requirements": -1}, "counts must be nonnegative"),
        ({"covered_requirements": 11}, "cannot exceed the total"),
        ({"uncovered_requirement_ids": ("REQ-1", "REQ-1")}, "must be unique"),
        ({"orphan_shape_count": -1}, "orphan shape count must be nonnegative"),
    ],
)
def test_a_coverage_reading_that_does_not_add_up_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """A reading covering more than exists is arithmetic nobody can account for."""

    with pytest.raises(ContractError, match=refusal):
        coverage(**kwargs)


def test_a_kind_nobody_measured_is_reported_as_unmeasured_and_a_short_one_by_how_short() -> None:
    """Unknown: a kind with no reading is not a kind with a reading of zero."""

    measured = coverage(coverage_by_kind={"screen": {"satisfied": 2}})
    assert measured.kind_shortfalls({"screen": 5}) == ("screen coverage is 2 of 5 required",)
    assert measured.kind_shortfalls({"screen": 2}) == ()
    unmeasured = coverage(coverage_by_kind={})
    assert unmeasured.kind_shortfalls({"screen": 5}) == ("screen coverage has not been measured",)
    # A threshold that is not a count constrains nothing and is skipped rather than guessed at.
    assert measured.kind_shortfalls({"screen": "many"}) == ()


def test_an_unmet_kind_obligation_becomes_a_gap_naming_the_requirement_and_the_shape() -> None:
    rows = coverage(unmet_kind_obligations=(("REQ-1", "screen"),)).gaps()
    assert any("REQ-1 requires a screen shape" in row.reason for row in rows)


# --------------------------------------------------------------------------------------
# launch bars — green only with evidence
# --------------------------------------------------------------------------------------


def gate_entry(**kwargs: Any) -> GateManifestEntry:
    fields: dict[str, Any] = {
        "gate_id": "PGM-fictional",
        "description": "a fictional launch bar",
        "predicate_kind": PredicateKind.FIXTURE,
        "status": GateStatus.OPEN,
        "launch_blocking": True,
        **kwargs,
    }
    return GateManifestEntry(**fields)


def test_a_green_bar_must_cite_its_evidence_and_an_open_one_must_not() -> None:
    """Recovery reads from the evidence reference, so a green bar without one says nothing."""

    assert gate_entry(status=GateStatus.GREEN, evidence_ref="activation:1").evidence_ref
    assert gate_entry().evidence_ref == ""
    with pytest.raises(ContractError, match="evidence_ref"):
        gate_entry(status=GateStatus.GREEN)
    with pytest.raises(ContractError, match="an open gate carries no evidence reference"):
        gate_entry(evidence_ref="activation:1")


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"gate_id": ""}, "gate_id"),
        ({"description": ""}, "gate description"),
        ({"predicate_kind": "fixture"}, "predicate kind is not recognized"),
        ({"status": "open"}, "gate status is not recognized"),
    ],
)
def test_a_launch_bar_that_cannot_be_read_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        gate_entry(**kwargs)


def test_a_manifest_refuses_two_bars_under_one_identity() -> None:
    """Identity: two bars with one id is one bar, and the other is lost."""

    entries = (gate_entry(), gate_entry(description="a different bar"))
    with pytest.raises(ContractError, match="gate ids must be unique"):
        ProductGateManifest(
            manifest_id="manifest-1",
            product_slug=SLUG,
            gates=entries,
            source_ref="activation:1",
            captured_at=NOW,
            snapshot_ref="snapshot:1",
        )


def test_a_manifest_version_counts_up_from_one() -> None:
    with pytest.raises(ContractError, match="version must be positive"):
        ProductGateManifest(
            manifest_id="manifest-1",
            product_slug=SLUG,
            gates=(),
            source_ref="activation:1",
            captured_at=NOW,
            snapshot_ref="snapshot:1",
            version=0,
        )


# --------------------------------------------------------------------------------------
# readiness — a verdict that agrees with its own reasons
# --------------------------------------------------------------------------------------


def readiness(**kwargs: Any) -> ReleaseReadiness:
    fields: dict[str, Any] = {
        "product_slug": SLUG,
        "readiness": Readiness.BLOCKED,
        "blocking_reasons": ("coverage is short",),
        "evaluated_at": NOW,
        "coverage_snapshot_id": "coverage:1",
        "validation_snapshot_id": "validation:1",
        "gate_manifest_id": "manifest-1",
        **kwargs,
    }
    return ReleaseReadiness(**fields)


def test_a_readiness_verdict_and_its_reasons_cannot_contradict_each_other() -> None:
    """A green carrying reasons, or a red carrying none, is a reading nobody can act on."""

    assert readiness().is_green is False
    assert readiness(readiness=Readiness.GREEN, blocking_reasons=()).is_green is True
    with pytest.raises(ContractError, match="green readiness carries no blocking reasons"):
        readiness(readiness=Readiness.GREEN)
    with pytest.raises(ContractError, match="must say why"):
        readiness(blocking_reasons=())
    with pytest.raises(ContractError, match="readiness is not recognized"):
        readiness(readiness="blocked")


def test_a_readiness_reading_renders_itself_for_the_record() -> None:
    row = readiness().as_dict()
    assert row["readiness"] == "blocked"
    assert row["blocking_reasons"] == ["coverage is short"]


# --------------------------------------------------------------------------------------
# the build-task mirror — the build system owns the truth
# --------------------------------------------------------------------------------------


def test_a_mirrored_task_records_the_state_the_build_system_reported() -> None:
    task = MirroredTask(
        task_id="task-1",
        batch_id="batch-1",
        external_task_id="external-1",
        rule="fictional-rule",
        claim_state=ClaimState.UNCLAIMED,
        fix_commands_present=True,
    )
    assert task.claim_state is ClaimState.UNCLAIMED
    with pytest.raises(ContractError, match="claim state is not recognized"):
        MirroredTask(
            task_id="task-1",
            batch_id="batch-1",
            external_task_id="external-1",
            rule="fictional-rule",
            claim_state="open",  # type: ignore[arg-type]
            fix_commands_present=True,
        )


def task_batch(**kwargs: Any) -> TaskBatch:
    fields: dict[str, Any] = {
        "batch_id": "batch-1",
        "binding_id": "binding-1",
        "product_slug": SLUG,
        "generated_by_move_id": "move-1",
        "batch_mode": "rule",
        "errors_only": True,
        "target_gap_count": 4,
        "tasks_created": 4,
        "coverage_snapshot_id": "coverage:1",
        "validation_snapshot_id": "validation:1",
        "created_at": NOW,
        **kwargs,
    }
    return TaskBatch(**fields)


def test_a_task_batch_names_the_move_that_generated_it() -> None:
    """Identity: generation is always a move, so a batch with no move behind it is orphaned."""

    assert task_batch().generated_by_move_id == "move-1"
    with pytest.raises(ContractError, match="generated_by_move_id"):
        task_batch(generated_by_move_id="")


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"batch_mode": "whatever"}, "batch mode must be rule or chain"),
        ({"target_gap_count": -1}, "batch counts must be nonnegative"),
        ({"tasks_created": -1}, "batch counts must be nonnegative"),
        ({"rule_filter": "   "}, "rule_filter"),
    ],
)
def test_a_batch_that_does_not_describe_real_work_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        task_batch(**kwargs)


def pipeline_decision(**kwargs: Any) -> PipelineGateDecision:
    fields: dict[str, Any] = {
        "decision_id": "decision-1",
        "product_slug": SLUG,
        "run_id": "run-1",
        "gate_kind": PipelineGateKind.RELEASE_READINESS,
        "from_state": ReleaseState.BUILDING,
        "to_state": ReleaseState.RELEASE_CANDIDATE,
        "outcome": PipelineOutcome.PASS,
        "reason": "every bar is met",
        "evaluated_at": NOW,
        **kwargs,
    }
    return PipelineGateDecision(**fields)


def test_a_pipeline_transition_records_where_it_moved_from_and_to() -> None:
    assert pipeline_decision().to_state is ReleaseState.RELEASE_CANDIDATE


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"reason": ""}, "reason"),
        ({"run_id": ""}, "run_id"),
        ({"gate_kind": "release_readiness"}, "pipeline gate kind is not recognized"),
        ({"outcome": "pass"}, "pipeline outcome is not recognized"),
        ({"from_state": "building"}, "from_state is not a recognized release state"),
        ({"to_state": "launched"}, "to_state is not a recognized release state"),
    ],
)
def test_a_transition_record_that_cannot_be_read_back_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        pipeline_decision(**kwargs)


def test_two_readings_of_the_same_registry_at_the_same_instant_share_one_identity() -> None:
    """Identity: the snapshot is what was read, so the same read is the same snapshot."""

    first = snapshot_identity(product_slug=SLUG, captured_at=NOW, registry_sha256=DIGEST)
    same = snapshot_identity(product_slug=SLUG, captured_at=NOW, registry_sha256=DIGEST)
    later = snapshot_identity(
        product_slug=SLUG, captured_at=NOW + dt.timedelta(seconds=1), registry_sha256=DIGEST
    )
    other = snapshot_identity(product_slug="another", captured_at=NOW, registry_sha256=DIGEST)
    assert first == same
    assert len({first, later, other}) == 3


# --------------------------------------------------------------------------------------
# registry — families, instances and the launch predicate
# --------------------------------------------------------------------------------------


def desk_family(**kwargs: Any) -> ProductFamily:
    fields: dict[str, Any] = {
        "key": ProductFamilyKey.SRG_DESK,
        "version": "1.0.0",
        "profile_kind": "DeskProfile",
        "required_profile_fields": (
            ProfileFieldSpec(name="mirror", field_type=ProfileFieldType.STRING),
            ProfileFieldSpec(name="verified_on", field_type=ProfileFieldType.STRING),
        ),
        "default_business_model": BusinessModelType.SUBSCRIPTION,
        "release_coverage_thresholds": {"verified_on_decay_days": 180},
        **kwargs,
    }
    return ProductFamily(**fields)


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"key": "srg_desk"}, "product family key is not recognized"),
        ({"default_business_model": "subscription"}, "default business model is not recognized"),
        ({"version": ""}, "family version"),
        ({"profile_kind": ""}, "profile_kind"),
        (
            {
                "required_profile_fields": (
                    ProfileFieldSpec(name="mirror", field_type=ProfileFieldType.STRING),
                    ProfileFieldSpec(name="mirror", field_type=ProfileFieldType.BOOLEAN),
                )
            },
            "uniquely named",
        ),
    ],
)
def test_a_family_that_could_not_select_its_cargo_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        desk_family(**kwargs)


def test_a_business_model_names_how_the_money_is_recognized() -> None:
    model = BusinessModel(BusinessModelType.SUBSCRIPTION, True, RevenueRecognition.OVER_TERM)
    assert model.as_dict()["revenue_recognition"] == "over_term"
    with pytest.raises(ContractError, match="business model type is not recognized"):
        BusinessModel("subscription", True, RevenueRecognition.OVER_TERM)  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="revenue recognition is not recognized"):
        BusinessModel(BusinessModelType.SUBSCRIPTION, True, "over_term")  # type: ignore[arg-type]


def desk_instance(**kwargs: Any) -> ProductInstance:
    profile_values: dict[str, Any] = {
        "mirror": "yes",
        "verified_on": TODAY.isoformat(),
        **kwargs.pop("profile_values", {}),
    }
    fields: dict[str, Any] = {
        "slug": SLUG,
        "family": ProductFamilyKey.SRG_DESK,
        "family_version": "1.0.0",
        "display_name": "A Fictional Desk",
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "owner_role": "fictional.owner",
        "business_model": BusinessModel(
            BusinessModelType.SUBSCRIPTION, True, RevenueRecognition.OVER_TERM
        ),
        "profile": FamilyProfile("DeskProfile", SLUG, profile_values),
        "release_state": ReleaseState.BUILDING,
        **kwargs,
    }
    return ProductInstance(**fields)


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"family": "srg_desk"}, "product family is not recognized"),
        ({"lifecycle_status": "active"}, "lifecycle status is not recognized"),
        ({"release_state": "building"}, "release state is not recognized"),
    ],
)
def test_an_instance_whose_state_is_not_one_of_the_declared_ones_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        desk_instance(**kwargs)


def test_a_launchable_desk_has_a_mirror_and_a_fresh_verification() -> None:
    """Control: every blocker below is absent here, so each one is its own reading."""

    assert launch_blockers(
        instance=desk_instance(), family=desk_family(), release_ready=True, today=TODAY
    ) == ()


@pytest.mark.parametrize(
    ("kwargs", "release_ready", "expected"),
    [
        ({}, False, "release readiness is not green"),
        ({"lifecycle_status": LifecycleStatus.RETIRED}, True, "a retired product cannot launch"),
        (
            {"profile_values": {"mirror": "no"}},
            True,
            "no raw mirror exists, so no claim can be derived",
        ),
        (
            {"profile_values": {"verified_on": "not-a-date"}},
            True,
            "verified_on is missing, so source freshness is unknown",
        ),
        (
            {"profile_values": {"verified_on": "2020-01-01"}},
            True,
            "source verification is older than 180 days",
        ),
    ],
)
def test_each_launch_blocker_is_its_own_reading_of_this_product(
    kwargs: dict[str, Any], release_ready: bool, expected: str
) -> None:
    """A launch predicate that could not say which condition stopped it is not actionable."""

    blockers = launch_blockers(
        instance=desk_instance(**kwargs),
        family=desk_family(),
        release_ready=release_ready,
        today=TODAY,
    )
    assert any(expected in blocker for blocker in blockers)


def test_an_internal_tool_is_not_marketing_launchable_unless_it_says_so() -> None:
    family = ProductFamily(
        key=ProductFamilyKey.INTERNAL_TOOL,
        version="1.0.0",
        profile_kind="ToolProfile",
        required_profile_fields=(),
        default_business_model=BusinessModelType.FREE,
    )
    def tool(allowed: Any) -> ProductInstance:
        return ProductInstance(
            slug=SLUG,
            family=ProductFamilyKey.INTERNAL_TOOL,
            family_version="1.0.0",
            display_name="A Fictional Tool",
            lifecycle_status=LifecycleStatus.ACTIVE,
            owner_role="fictional.owner",
            business_model=BusinessModel(
                BusinessModelType.FREE, False, RevenueRecognition.NONE
            ),
            profile=FamilyProfile("ToolProfile", SLUG, {"public_marketing_allowed": allowed}),
            release_state=ReleaseState.BUILDING,
        )

    blocked = launch_blockers(
        instance=tool(False), family=family, release_ready=True, today=TODAY
    )
    assert any("not marketing-launch-eligible" in row for row in blocked)
    assert launch_blockers(
        instance=tool(True), family=family, release_ready=True, today=TODAY
    ) == ()


def test_a_profile_missing_a_declared_field_is_refused_with_that_field_named() -> None:
    validation = validate_family_profile(
        desk_family(), FamilyProfile("DeskProfile", SLUG, {"mirror": "yes"})
    )
    assert validation.accepted is False
    assert any("verified_on" in reason for reason in validation.reasons)
    assert validate_family_profile(desk_family(), desk_instance().profile).accepted is True


def test_a_profile_of_the_wrong_kind_is_refused_before_its_fields_are_read() -> None:
    validation = validate_family_profile(
        desk_family(), FamilyProfile("SomethingElse", SLUG, {})
    )
    assert validation.accepted is False
    assert any("does not match family" in reason for reason in validation.reasons)


def test_a_product_declaring_the_wrong_family_version_is_refused_by_registration() -> None:
    """Recovery: the reason names both versions, so somebody knows which to move."""

    registry = FamilyRegistry((desk_family(),))
    refusal = register_product(
        registry=registry,
        instance=desk_instance(family_version="2.0.0"),
        manifest=manifest(SLUG),
        detected_at=NOW,
    )
    assert refusal is not None
    assert "family version 2.0.0" in refusal.reason


def test_a_manifest_belonging_to_another_product_is_refused_by_registration() -> None:
    registry = FamilyRegistry((desk_family(),))
    refusal = register_product(
        registry=registry,
        instance=desk_instance(),
        manifest=manifest("somebody-else"),
        detected_at=NOW,
    )
    assert refusal is not None
    assert "belongs to a different product" in refusal.reason


def test_an_incomplete_profile_is_refused_with_a_gap_for_each_missing_field() -> None:
    registry = FamilyRegistry((desk_family(),))
    refusal = register_product(
        registry=registry,
        instance=desk_instance(profile_values={"verified_on": ""}),
        manifest=manifest(SLUG),
        detected_at=NOW,
    )
    assert refusal is not None
    assert refusal.reason.startswith("incomplete_family_profile:")
    assert all(gap.gap_type == "incomplete_family_profile" for gap in refusal.gaps)


def test_a_shared_asset_names_one_owner_and_distinct_consumers() -> None:
    asset = SharedAssetBinding(
        asset_id="care-schema",
        asset_kind=SharedAssetKind.TAXONOMY,
        owner_product=SLUG,
        consumer_products=("another-product",),
        change_policy="owner approves, consumers acknowledge",
        created_at=NOW,
    )
    assert asset.is_active is True
    with pytest.raises(ContractError, match="shared asset kind is not recognized"):
        SharedAssetBinding(
            asset_id="care-schema",
            asset_kind="schema",  # type: ignore[arg-type]
            owner_product=SLUG,
            consumer_products=("another-product",),
            change_policy="owner approves",
            created_at=NOW,
        )
    with pytest.raises(ContractError, match="consumers must be unique"):
        SharedAssetBinding(
            asset_id="care-schema",
            asset_kind=SharedAssetKind.TAXONOMY,
            owner_product=SLUG,
            consumer_products=("another-product", "another-product"),
            change_policy="owner approves",
            created_at=NOW,
        )
    with pytest.raises(ContractError, match="status must be active or superseded"):
        SharedAssetBinding(
            asset_id="care-schema",
            asset_kind=SharedAssetKind.TAXONOMY,
            owner_product=SLUG,
            consumer_products=("another-product",),
            change_policy="owner approves",
            created_at=NOW,
            status="retired",
        )


# --------------------------------------------------------------------------------------
# scheduling — a shared channel, and the cross-product cadence
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"key": ""}, "channel key"),
        ({"kind": "email_domain"}, "channel kind is not recognized"),
        ({"state": "active"}, "channel state is not recognized"),
        ({"product_slugs": ()}, "must name the products that share it"),
        ({"product_slugs": (SLUG, SLUG)}, "channel products must be unique"),
    ],
)
def test_a_channel_that_does_not_say_who_shares_it_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """The shared-channel carve-out is the one sanctioned cross-product effect.

    It rests entirely on the channel knowing which products share it, so a channel that
    cannot say is refused rather than treated as belonging to nobody.
    """

    fields: dict[str, Any] = {
        "key": "fictional-domain",
        "kind": ChannelKind.EMAIL_DOMAIN,
        "state": ChannelState.ACTIVE,
        "product_slugs": (SLUG,),
        **kwargs,
    }
    with pytest.raises(ContractError, match=refusal):
        Channel(**fields)


def test_a_channel_renders_its_state_for_the_record() -> None:
    row = Channel(
        key="fictional-domain",
        kind=ChannelKind.EMAIL_DOMAIN,
        state=ChannelState.ACTIVE,
        product_slugs=(SLUG,),
    ).as_dict()
    assert row["state"] == "active"
    assert row["cooldown_until"] is None


def sweep(**kwargs: Any) -> SweepPlan:
    fields: dict[str, Any] = {
        "sweep_id": "sweep-1",
        "product_slugs": (SLUG, "another-product"),
        "tasks": ("refresh_coverage",),
        "scheduled_for": NOW,
        **kwargs,
    }
    return SweepPlan(**fields)


def test_a_sweep_covers_the_products_it_names_and_excludes_the_rest() -> None:
    """The cross-product cadence. Nothing on the per-move path waits for it."""

    plan = sweep()
    assert plan.excludes("a-third-product") is True
    assert plan.excludes(SLUG) is False


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"sweep_id": ""}, "sweep_id"),
        ({"product_slugs": ()}, "must name the products it covers"),
        ({"tasks": ()}, "must name the work it performs"),
        ({"product_slugs": (SLUG, SLUG)}, "sweep products must be unique"),
        ({"tasks": ("refresh", "refresh")}, "sweep tasks must be unique"),
        ({"product_slugs": (SLUG, "")}, "sweep product"),
    ],
)
def test_a_sweep_that_is_not_bounded_is_refused(kwargs: dict[str, Any], refusal: str) -> None:
    """An unbounded sweep is an archive-wide scan wearing a plan's name."""

    with pytest.raises(ContractError, match=refusal):
        sweep(**kwargs)
