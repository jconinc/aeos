"""Two products, one core: what each family must declare, and what it may not borrow."""

from __future__ import annotations

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapSeverity
from aeos_kernel.modules import Module, ModuleRegistry, MoveFamily, PriorityClass, load_modules
from aeos_kernel.registry import (
    FamilyProfile,
    LiabilityClass,
    SharedAssetBinding,
    SharedAssetKind,
    launch_blockers,
    register_product,
    retire_blocked_by_shared_assets,
    validate_family_profile,
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


def test_two_families_run_on_the_same_core_without_borrowing_each_other_s_fields() -> None:
    registry = family_registry()
    desk, app = desk_instance(), app_instance()
    # The desk takes payment, so its manifest names the commercial module; the app does not.
    assert register_product(
        registry=registry,
        instance=desk,
        manifest=manifest(desk.slug, modules=("pipeline", "commercial")),
        detected_at=NOW,
    ) is None
    assert register_product(
        registry=registry, instance=app, manifest=manifest(app.slug), detected_at=NOW
    ) is None
    # The desk's mirror field is a desk concept. Asking an app for it yields the family
    # default, not the other product's value.
    assert desk.profile_value("mirror", DESK_FAMILY) == "yes"
    assert app.profile_value("mirror", APP_FAMILY) is None
    assert app.profile_value("age_gated", APP_FAMILY) is False


def test_a_product_of_an_unregistered_family_never_runs() -> None:
    from aeos_kernel.registry import FamilyRegistry

    refusal = register_product(
        registry=FamilyRegistry((APP_FAMILY,)),
        instance=desk_instance(),
        manifest=manifest("fictional-desk"),
        detected_at=NOW,
    )
    assert refusal is not None
    assert "not registered" in refusal.reason


def test_a_missing_family_field_fails_creation_rather_than_defaulting() -> None:
    instance = desk_instance()
    stripped = FamilyProfile(
        "DeskProfile",
        instance.slug,
        {key: value for key, value in instance.profile.fields.items() if key != "mirror"},
    )
    result = validate_family_profile(DESK_FAMILY, stripped)
    assert not result.accepted
    assert any("mirror is required" in reason for reason in result.reasons)


def test_a_field_the_family_never_declared_is_refused_at_the_door() -> None:
    instance = desk_instance()
    smuggled = FamilyProfile(
        "DeskProfile", instance.slug, {**instance.profile.fields, "secret_flag": True}
    )
    result = validate_family_profile(DESK_FAMILY, smuggled)
    assert not result.accepted
    assert any("secret_flag is not declared" in reason for reason in result.reasons)


def test_a_profile_from_another_family_is_not_accepted_by_name_alone() -> None:
    result = validate_family_profile(DESK_FAMILY, app_instance().profile)
    assert not result.accepted
    assert "does not match family" in result.reasons[0]


def test_the_liability_class_must_agree_between_profile_and_manifest() -> None:
    refusal = register_product(
        registry=family_registry(),
        instance=desk_instance(),
        manifest=manifest("fictional-desk", liability_class=LiabilityClass.C),
        detected_at=NOW,
    )
    assert refusal is not None
    assert "liability class disagrees" in refusal.reason


def test_a_product_that_takes_payment_needs_its_commercial_module_named() -> None:
    """A billing product whose manifest omits commercial surfaces the dependency as a gap."""

    refusal = register_product(
        registry=family_registry(),
        instance=desk_instance(),
        manifest=manifest("fictional-desk", modules=("pipeline",)),
        detected_at=NOW,
    )
    assert refusal is not None
    assert refusal.reason == "commercial_dependency_unsatisfied"
    assert refusal.gaps[0].gap_type == "commercial_module_not_enabled"


def test_a_billing_product_registers_once_the_module_is_enabled() -> None:
    """The control for the previous case: the same product passes with the module named."""

    assert register_product(
        registry=family_registry(),
        instance=desk_instance(),
        manifest=manifest("fictional-desk", modules=("pipeline", "commercial")),
        detected_at=NOW,
    ) is None


def test_consuming_a_shared_asset_without_declaring_it_is_a_validator_error() -> None:
    binding = SharedAssetBinding(
        asset_id="fictional-entity-graph",
        asset_kind=SharedAssetKind.ENTITY_GRAPH,
        owner_product="fictional-anchor",
        consumer_products=("fictional-app",),
        change_policy="owner approval plus every consumer's acknowledgment",
        created_at=NOW,
    )
    refusal = register_product(
        registry=family_registry(),
        instance=app_instance(),
        manifest=manifest("fictional-app"),
        shared_assets_consumed=(),
        shared_asset_bindings=(binding,),
        detected_at=NOW,
    )
    assert refusal is not None
    assert refusal.gaps[0].gap_type == "shared_asset_undeclared"


def test_declaring_a_shared_asset_with_no_active_binding_is_a_gap() -> None:
    refusal = register_product(
        registry=family_registry(),
        instance=app_instance(),
        manifest=manifest("fictional-app"),
        shared_assets_consumed=("fictional-entity-graph",),
        shared_asset_bindings=(),
        detected_at=NOW,
    )
    assert refusal is not None
    assert refusal.gaps[0].gap_type == "shared_asset_unbound"
    assert refusal.gaps[0].severity is GapSeverity.ERROR


def test_retiring_the_owner_of_a_live_shared_asset_is_blocked_while_consumers_exist() -> None:
    binding = SharedAssetBinding(
        asset_id="fictional-entity-graph",
        asset_kind=SharedAssetKind.ENTITY_GRAPH,
        owner_product="fictional-anchor",
        consumer_products=("fictional-app", "fictional-desk"),
        change_policy="owner approval plus every consumer's acknowledgment",
        created_at=NOW,
    )
    blocking = retire_blocked_by_shared_assets(
        product_slug="fictional-anchor", bindings=(binding,)
    )
    assert [item.asset_id for item in blocking] == ["fictional-entity-graph"]
    # A consumer retiring takes nothing away from anyone, so nothing blocks it.
    assert retire_blocked_by_shared_assets(product_slug="fictional-app", bindings=(binding,)) == ()


def test_an_owner_cannot_be_listed_as_its_own_consumer() -> None:
    with pytest.raises(ContractError):
        SharedAssetBinding(
            asset_id="fictional-entity-graph",
            asset_kind=SharedAssetKind.ENTITY_GRAPH,
            owner_product="fictional-anchor",
            consumer_products=("fictional-anchor",),
            change_policy="owner approval",
            created_at=NOW,
        )


def test_launch_is_family_aware_rather_than_one_rule_for_every_product() -> None:
    unmirrored = desk_instance(mirror="no")
    blockers = launch_blockers(
        instance=unmirrored, family=DESK_FAMILY, release_ready=True, today=TODAY
    )
    assert any("no raw mirror" in reason for reason in blockers)
    # The same predicate on a consumer app does not invent a mirror requirement.
    assert launch_blockers(
        instance=app_instance(), family=APP_FAMILY, release_ready=True, today=TODAY
    ) == ()


def test_a_desk_whose_source_check_has_decayed_cannot_launch() -> None:
    stale = desk_instance(verified_on="2025-01-01")
    blockers = launch_blockers(
        instance=stale, family=DESK_FAMILY, release_ready=True, today=TODAY
    )
    assert any("older than 180 days" in reason for reason in blockers)


def test_readiness_that_is_not_green_blocks_launch_for_every_family() -> None:
    for instance, family in ((desk_instance(), DESK_FAMILY), (app_instance(), APP_FAMILY)):
        blockers = launch_blockers(
            instance=instance, family=family, release_ready=False, today=TODAY
        )
        assert "release readiness is not green" in blockers


def test_a_module_whose_credential_scope_is_absent_refuses_with_a_readable_gap() -> None:
    registry = ModuleRegistry((pipeline_module(), outreach_module()))
    loaded = load_modules(
        registry=registry,
        manifest=manifest("fictional-app", modules=("pipeline", "outreach"), credential_scopes={}),
        available_rails=PIPELINE_RAILS,
        detected_at=NOW,
    )
    assert [module.key for module in loaded.active] == ["pipeline"]
    assert "outreach" in loaded.refused
    reason = next(gap.reason for gap in loaded.gaps if gap.subject_ref == "outreach")
    assert "credential scope" in reason


def test_the_same_module_activates_once_its_credential_scope_is_granted() -> None:
    """Control: the refusal above is about the missing scope, not the module itself."""

    registry = ModuleRegistry((pipeline_module(), outreach_module()))
    loaded = load_modules(
        registry=registry,
        manifest=manifest("fictional-app", modules=("pipeline", "outreach")),
        available_rails=PIPELINE_RAILS,
        detected_at=NOW,
    )
    assert sorted(module.key for module in loaded.active) == ["outreach", "pipeline"]
    assert loaded.refused == ()
    assert "post_update" in loaded.move_types


def test_a_module_whose_dependency_was_not_enabled_does_not_half_load() -> None:
    registry = ModuleRegistry((pipeline_module(), outreach_module()))
    loaded = load_modules(
        registry=registry,
        manifest=manifest("fictional-app", modules=("outreach",)),
        available_rails=PIPELINE_RAILS,
        detected_at=NOW,
    )
    assert loaded.active == ()
    assert "outreach" in loaded.refused
    assert any(gap.gap_type == "module_dependency_unsatisfied" for gap in loaded.gaps)


def test_a_move_type_with_no_rail_anywhere_fails_registration_rather_than_running_ungated() -> None:
    registry = ModuleRegistry((pipeline_module(),))
    loaded = load_modules(
        registry=registry,
        manifest=manifest("fictional-app", modules=("pipeline",)),
        available_rails=frozenset({"pipeline.requires_active_binding"}),
        detected_at=NOW,
    )
    assert loaded.active == ()
    gap = next(gap for gap in loaded.gaps if gap.gap_type == "move_type_ungated")
    assert "pipeline.requires_green_readiness" in gap.reason


def test_one_move_type_cannot_be_claimed_by_two_modules() -> None:
    clashing = Module(
        key="other",
        version="1.0.0",
        rule_profile_ref="fictional.other@1",
        move_families=(
            MoveFamily(
                move_type="capture_coverage",
                module_key="other",
                priority_class=PriorityClass.NORMAL,
                owner_role="fictional.owner",
                approval_policy="fictional.owner_attested",
                evidence_kinds=("x",),
                rails=("other.rail",),
            ),
        ),
    )
    registry = ModuleRegistry((pipeline_module(),))
    with pytest.raises(ContractError) as error:
        registry.register(clashing)
    assert "already registered by module" in str(error.value)


def test_a_dual_control_family_must_also_park_and_never_graduate() -> None:
    with pytest.raises(ContractError):
        MoveFamily(
            move_type="fictional_money_move",
            module_key="pipeline",
            priority_class=PriorityClass.PRIORITY,
            owner_role="fictional.owner",
            approval_policy="fictional.owner_attested",
            evidence_kinds=("ledger_row",),
            rails=("pipeline.requires_active_binding",),
            dual_control=True,
        )


def test_an_actor_outside_the_declared_roles_is_not_permitted() -> None:
    family = pipeline_module().family("launch_product")
    assert family is not None
    assert family.permits_actor("fictional.owner")
    assert not family.permits_actor("fictional.contractor")
    # An unrestricted family does not silently deny everyone.
    assert pipeline_module().family("capture_coverage").permits_actor("anybody")  # type: ignore[union-attr]


def test_one_product_s_module_failure_leaves_the_other_product_untouched() -> None:
    registry = ModuleRegistry((pipeline_module(), outreach_module()))
    broken = load_modules(
        registry=registry,
        manifest=manifest("fictional-app", modules=("pipeline", "outreach"), credential_scopes={}),
        available_rails=PIPELINE_RAILS,
        detected_at=NOW,
    )
    healthy = load_modules(
        registry=registry,
        manifest=manifest("fictional-desk", modules=("pipeline", "outreach")),
        available_rails=PIPELINE_RAILS,
        detected_at=NOW,
    )
    assert broken.refused == ("outreach",)
    assert healthy.refused == ()
    assert all(gap.product_slug == "fictional-app" for gap in broken.gaps)
